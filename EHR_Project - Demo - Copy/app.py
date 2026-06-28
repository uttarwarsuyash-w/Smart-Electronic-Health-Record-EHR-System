import sqlite3
import os
import json
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

from flask import Flask, jsonify, redirect, render_template, request, session, url_for

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

if load_dotenv:
    load_dotenv()

app = Flask(__name__, template_folder="template")
app.secret_key = "ehr_project_secret_key"
BASE_DIR = Path(__file__).resolve().parent
DATABASE = BASE_DIR / os.environ.get("EHR_DATABASE", "ehr_working.db")
UPLOAD_FOLDER = BASE_DIR / "static" / "lab_reports"
DEFAULT_OLLAMA_BASE_URL = "http://127.0.0.1:11434"
DEFAULT_OLLAMA_MODEL = "llama3.2:3b"


def get_connection():
    conn = sqlite3.connect(DATABASE, timeout=10)
    conn.execute("PRAGMA journal_mode=MEMORY")
    return conn


def get_patient_by_custom_id(patient_custom_id):
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM Patient
        WHERE Patient_Custom_ID = ?
    """, (patient_custom_id,))

    patient = cursor.fetchone()
    conn.close()
    return patient


def get_doctor_by_custom_id(doctor_custom_id):
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM Doctor
        WHERE Doctor_Custom_ID = ?
    """, (doctor_custom_id,))

    doctor = cursor.fetchone()
    conn.close()
    return doctor


@app.context_processor
def inject_current_doctor():
    doctor_custom_id = session.get("doctor_custom_id")

    if not doctor_custom_id:
        return {"current_doctor": None}

    return {
        "current_doctor": {
            "id": doctor_custom_id,
            "name": session.get("doctor_name", "Doctor")
        }
    }


def get_consultations_by_doctor(doctor_custom_id):
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT Consultation_ID, Patient_Custom_ID, Consultation_Date, Lab_Report
        FROM Consultation
        WHERE Doctor_Custom_ID = ?
        ORDER BY Consultation_No DESC
    """, (doctor_custom_id,))

    consultations = cursor.fetchall()
    conn.close()
    return consultations


def get_consultations_by_patient(patient_custom_id):
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT Consultation_ID, Patient_Custom_ID, Doctor_Custom_ID,
               Consultation_Date, Lab_Report
        FROM Consultation
        WHERE Patient_Custom_ID = ?
        ORDER BY Consultation_No DESC
    """, (patient_custom_id,))

    consultations = cursor.fetchall()
    conn.close()
    return consultations


def get_patient_summary_records(patient_custom_id):
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT Consultation_Date, Complaints, Symptoms, Consultation_Notes,
               Conclusion, Prescription, Doctor_Custom_ID
        FROM Consultation
        WHERE Patient_Custom_ID = ?
        ORDER BY Consultation_Date ASC, Consultation_No ASC
    """, (patient_custom_id,))

    records = cursor.fetchall()
    conn.close()
    return records


def get_consultation_by_id(consultation_id):
    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM Consultation
        WHERE Consultation_ID = ?
    """, (consultation_id,))

    consultation = cursor.fetchone()
    conn.close()
    return consultation


def add_column(table_name, column_name, column_type):
    conn = get_connection()
    cursor = conn.cursor()
    cursor.execute(f"PRAGMA table_info({table_name})")
    columns = cursor.fetchall()

    column_exists = False
    for column in columns:
        if column[1] == column_name:
            column_exists = True

    if column_exists == False:
        cursor.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}")
        conn.commit()

    conn.close()


def create_tables():
    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Patient(
            Patient_ID INTEGER PRIMARY KEY AUTOINCREMENT,
            Patient_Custom_ID TEXT UNIQUE,
            Name TEXT,
            Father_Husband_Name TEXT,
            Gender TEXT,
            Age INTEGER,
            DOB TEXT,
            Blood_Group TEXT,
            Height REAL,
            Weight REAL,
            Address TEXT,
            City TEXT,
            State TEXT,
            Mobile_no TEXT,
            Email TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Doctor(
            DOCTOR_ID INTEGER PRIMARY KEY AUTOINCREMENT,
            Doctor_Custom_ID TEXT UNIQUE,
            Name TEXT,
            Specialization TEXT,
            Hospital_name TEXT,
            City TEXT,
            State TEXT,
            NMR_ID TEXT,
            Mobile TEXT,
            Email TEXT
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS Consultation(
            Consultation_No INTEGER PRIMARY KEY AUTOINCREMENT,
            Consultation_ID TEXT UNIQUE,
            Patient_Custom_ID TEXT,
            Doctor_Custom_ID TEXT,
            Consultation_Date TEXT,
            Consultation_Day TEXT,
            Consultation_Time TEXT,
            Complaints TEXT,
            Symptoms TEXT,
            Consultation_Notes TEXT,
            Conclusion TEXT,
            Prescription TEXT,
            Lab_Report TEXT
        )
    """)
    
    cursor.execute("""
CREATE TABLE IF NOT EXISTS Appointment(
    Appointment_ID INTEGER PRIMARY KEY AUTOINCREMENT,
    Patient_Custom_ID TEXT,
    Doctor_Custom_ID TEXT,
    Appointment_Date TEXT,
    Appointment_Time TEXT,
    Status TEXT
)
""")

    conn.commit()
    conn.close()

    add_column("Patient", "Patient_Custom_ID", "TEXT")
    add_column("Patient", "Father_Husband_Name", "TEXT")
    add_column("Patient", "Address", "TEXT")
    add_column("Patient", "City", "TEXT")
    add_column("Patient", "State", "TEXT")
    add_column("Doctor", "Doctor_Custom_ID", "TEXT")
    add_column("Consultation", "Lab_Report", "TEXT")
    UPLOAD_FOLDER.mkdir(parents=True, exist_ok=True)


def make_code_part(value, size, fill_char):
    value = str(value).upper()
    final_value = ""

    for letter in value:
        if letter.isalnum():
            final_value = final_value + letter

    final_value = final_value[:size]

    while len(final_value) < size:
        final_value = final_value + fill_char

    return final_value


def make_patient_id(name, dob, patient_id):
    name_part = make_code_part(name, 2, "X")
    dob_part = make_code_part(str(dob).replace("-", ""), 2, "0")
    return "P0" + name_part + dob_part + str(patient_id).zfill(4)


def make_doctor_id(name, specialization, doctor_id):
    name_part = make_code_part(name, 2, "X")
    specialization_part = make_code_part(specialization, 2, "X")
    return "D0" + name_part + specialization_part + str(doctor_id).zfill(4)


def make_consultation_id(date_text, consultation_no):
    date_value = datetime.strptime(date_text, "%Y-%m-%d")
    date_part = date_value.strftime("%d%m")
    return "T0" + date_part + str(consultation_no).zfill(4)


def get_day_name(date_text):
    date_value = datetime.strptime(date_text, "%Y-%m-%d")
    return date_value.strftime("%A")


def clean_file_name(file_name):
    final_name = ""

    for letter in file_name:
        if letter.isalnum() or letter in [".", "_", "-"]:
            final_name = final_name + letter

    return final_name


def get_ollama_base_url():
    return os.environ.get("OLLAMA_BASE_URL", DEFAULT_OLLAMA_BASE_URL).rstrip("/")


def get_ollama_model():
    return os.environ.get("OLLAMA_MODEL", DEFAULT_OLLAMA_MODEL)


def get_ollama_error_message(error):
    if isinstance(error, urllib.error.HTTPError):
        return (
            f"AI summary could not be generated with Ollama model "
            f"'{get_ollama_model()}'. Make sure it is installed with "
            f"'ollama pull {get_ollama_model()}'."
        )

    if isinstance(error, urllib.error.URLError):
        return (
            "AI summary could not connect to Ollama. Open the Ollama app or run "
            "'ollama serve', then try again."
        )

    return (
        "AI summary could not be generated with local Ollama right now. "
        "Please check that Ollama is running and the model is installed."
    )


def generate_ollama_summary(prompt):
    payload = {
        "model": get_ollama_model(),
        "prompt": prompt,
        "stream": False,
        "options": {
            "temperature": 0.1,
            "num_predict": 180
        }
    }
    request_data = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(
        f"{get_ollama_base_url()}/api/generate",
        data=request_data,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    with urllib.request.urlopen(request, timeout=120) as response:
        response_data = json.loads(response.read().decode("utf-8"))

    return response_data.get("response", "").strip()


def summarize_patient_history(records):
    if len(records) == 0:
        return "No previous consultation history is available for this patient."

    history_text = ""

    for record in records:
        history_text = history_text + f"""
Date: {record["Consultation_Date"]}
Chief complaint: {record["Complaints"]}
Symptoms: {record["Symptoms"]}
Consultation notes: {record["Consultation_Notes"]}
Diagnosis/Conclusion: {record["Conclusion"]}
Prescription: {record["Prescription"]}
"""

    prompt = f"""
You are an AI assistant helping doctors quickly review a patient's complete consultation history inside an Electronic Health Record (EHR) system.

Your task is to generate a professional medical summary strictly using the consultation records provided below.

Instructions:
- Write a concise but information-rich summary in paragraph form.
- Maintain proper chronological order of consultations.
- Mention each doctor's consultation separately in sequence.
- Clearly describe:
  - patient's recurring complaints and symptoms,
  - important findings,
  - diagnosis or clinical impression given by each doctor,
  - medications or treatment advised,
  - response to treatment or symptom progression,
  - investigations/tests recommended or performed,
  - any worsening, improvement, or new symptoms.
- Mention the approximate number of days between consultations whenever possible.
- Highlight long-term conditions, repeated complaints, and important medical patterns.
- If different doctors provided similar conclusions, summarize the trend clearly.
- If information is missing, do not assume or invent details.
- Do not create diagnoses, medications, allergies, or observations that are not explicitly mentioned.
- Keep the tone professional, medically clear, and suitable for doctors reviewing an EHR dashboard.
- Make the summary easy to understand within 15–25 seconds of reading.
- Return only the final summary paragraph.
- Do not use bullet points, headings, introductions, notes, or disclaimers.

Patient consultation history:

{history_text}
"""

    try:
        summary = generate_ollama_summary(prompt)

        if summary == "":
            return "AI summary could not be generated for this patient by local Ollama."

        return summary
    except Exception as error:
        print("Ollama summary error:", error)
        return get_ollama_error_message(error)


@app.route("/")
def home():
    session.pop("doctor_custom_id", None)
    session.pop("doctor_name", None)
    return render_template("home.html")
 

@app.route("/patient")
def patient_form():
    return render_template("index.html", page="patient")


@app.route("/doctor")
def doctor_home():
    return render_template("doctor_home.html")


@app.route("/doctor_register")
def doctor_form():
    return render_template("index.html", page="doctor")


@app.route("/doctor_login", methods=["POST"])
def doctor_login():
    doctor_custom_id = request.form["doctor_custom_id"]
    mobile = request.form["mobile"]

    conn = get_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM Doctor
        WHERE Doctor_Custom_ID = ? AND Mobile = ?
    """, (doctor_custom_id, mobile))

    doctor = cursor.fetchone()
    conn.close()

    if doctor:
        session["doctor_custom_id"] = doctor_custom_id
        session["doctor_name"] = doctor["Name"]
        return render_template(
            "doctor_dashboard.html",
            doctor_id=doctor_custom_id
        )
    else:
        return render_template(
            "doctor_home.html",
            error="Invalid credentials. Please check Doctor ID and mobile number."
        )


@app.route("/start_consultation")
def start_consultation():
    if "doctor_custom_id" not in session:
        return redirect(url_for("doctor_home"))

    return render_template("start_consultation.html")


@app.route("/find_patient", methods=["POST"])
def find_patient():
    if "doctor_custom_id" not in session:
        return redirect(url_for("doctor_home"))

    patient_custom_id = request.form["patient_custom_id"]
    patient = get_patient_by_custom_id(patient_custom_id)

    if patient:
        return render_template(
            "start_consultation.html",
            patient=patient
        )
    else:
        return render_template(
            "start_consultation.html",
            error="Patient ID not found."
        )


@app.route("/past_consultation")
def past_consultation():
    if "doctor_custom_id" not in session:
        return redirect(url_for("doctor_home"))

    doctor_custom_id = session["doctor_custom_id"]
    consultations = get_consultations_by_doctor(doctor_custom_id)

    return render_template(
        "past_consultation.html",
        consultations=consultations
    )


@app.route("/view_consultation/<consultation_id>")
def view_consultation(consultation_id):
    if "doctor_custom_id" not in session:
        return redirect(url_for("doctor_home"))

    doctor_custom_id = session["doctor_custom_id"]
    consultation = get_consultation_by_id(consultation_id)

    if consultation:
        patient = get_patient_by_custom_id(consultation["Patient_Custom_ID"])
        doctor = get_doctor_by_custom_id(consultation["Doctor_Custom_ID"])

        return render_template(
            "view_consultation.html",
            consultation=consultation,
            patient=patient,
            doctor=doctor
        )
    else:
        return render_template(
            "past_consultation.html",
            consultations=get_consultations_by_doctor(doctor_custom_id),
            error="Consultation record not found."
        )


@app.route("/patient_history", methods=["POST"])
def patient_history():
    if "doctor_custom_id" not in session:
        return redirect(url_for("doctor_home"))

    patient_custom_id = request.form["patient_custom_id"]
    patient = get_patient_by_custom_id(patient_custom_id)
    consultations = get_consultations_by_patient(patient_custom_id)

    return render_template(
        "patient_history.html",
        patient=patient,
        consultations=consultations
    )


@app.route("/ai_patient_summary/<patient_custom_id>")
def ai_patient_summary(patient_custom_id):
    if "doctor_custom_id" not in session:
        return jsonify({
            "success": False,
            "summary": "Please login as doctor to generate patient summary."
        }), 401

    patient = get_patient_by_custom_id(patient_custom_id)

    if not patient:
        return jsonify({
            "success": False,
            "summary": "Patient record not found."
        }), 404

    records = get_patient_summary_records(patient_custom_id)
    summary = summarize_patient_history(records)

    return jsonify({
        "success": True,
        "summary": summary
    })


@app.route("/consultation_form", methods=["POST"])
def consultation_form():
    if "doctor_custom_id" not in session:
        return redirect(url_for("doctor_home"))

    patient_custom_id = request.form["patient_custom_id"]
    doctor_custom_id = session["doctor_custom_id"]

    patient = get_patient_by_custom_id(patient_custom_id)
    doctor = get_doctor_by_custom_id(doctor_custom_id)

    if patient and doctor:
        return render_template(
            "consultation_form.html",
            patient=patient,
            doctor=doctor
        )
    else:
        return render_template(
            "start_consultation.html",
            error="Patient or doctor details not found."
        )


@app.route("/save_consultation", methods=["POST"])
def save_consultation():
    if "doctor_custom_id" not in session:
        return redirect(url_for("doctor_home"))

    patient_custom_id = request.form["patient_custom_id"]
    doctor_custom_id = request.form["doctor_custom_id"]
    consultation_date = request.form["consultation_date"]
    consultation_day = get_day_name(consultation_date)
    consultation_time = request.form["consultation_time"]
    complaints = request.form["complaints"]
    symptoms = request.form["symptoms"]
    consultation_notes = request.form["consultation_notes"]
    conclusion = request.form["conclusion"]
    prescription = request.form["prescription"]
    lab_report_name = ""

    lab_report = request.files.get("lab_report")

    if lab_report and lab_report.filename != "":
        lab_report_name = clean_file_name(lab_report.filename)
        lab_report.save(UPLOAD_FOLDER / lab_report_name)

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO Consultation
        (Patient_Custom_ID, Doctor_Custom_ID, Consultation_Date,
         Consultation_Day, Consultation_Time, Complaints, Symptoms,
         Consultation_Notes, Conclusion, Prescription, Lab_Report)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        patient_custom_id, doctor_custom_id, consultation_date,
        consultation_day, consultation_time, complaints, symptoms,
        consultation_notes, conclusion, prescription, lab_report_name
    ))

    consultation_no = cursor.lastrowid
    consultation_id = make_consultation_id(consultation_date, consultation_no)

    cursor.execute("""
        UPDATE Consultation
        SET Consultation_ID = ?
        WHERE Consultation_No = ?
    """, (consultation_id, consultation_no))

    conn.commit()
    conn.close()

    return render_template(
        "consultation_success.html",
        consultation_id=consultation_id,
        consultation_day=consultation_day
    )


@app.route("/add_patient", methods=["POST"])
def add_patient():
    name = request.form["name"]
    father_husband_name = request.form["father_husband_name"]
    gender = request.form["gender"]
    age = request.form["age"]
    dob = request.form["dob"]
    blood_group = request.form["blood_group"]
    height = request.form["height"]
    weight = request.form["weight"]
    address = request.form["address"]
    city = request.form["city"]
    state = request.form["state"]
    mobile = request.form["mobile"]
    email = request.form["email"]

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO Patient
        (Name, Father_Husband_Name, Gender, Age, DOB, Blood_Group, Height,
         Weight, Address, City, State, Mobile_no, Email)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        name, father_husband_name, gender, age, dob, blood_group, height,
        weight, address, city, state, mobile, email
    ))

    patient_id = cursor.lastrowid
    patient_custom_id = make_patient_id(name, dob, patient_id)

    cursor.execute("""
        UPDATE Patient
        SET Patient_Custom_ID = ?
        WHERE Patient_ID = ?
    """, (patient_custom_id, patient_id))

    conn.commit()
    conn.close()

    return render_template(
        "index.html",
        page="patient",
        message="Patient registered successfully.",
        generated_id=patient_custom_id
    )


@app.route("/add_doctor", methods=["POST"])
def add_doctor():
    name = request.form["name"]
    specialization = request.form["specialization"]
    hospital_name = request.form["hospital_name"]
    city = request.form["city"]
    state = request.form["state"]
    nmr_id = request.form["nmr_id"]
    mobile = request.form["mobile"]
    email = request.form["email"]

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
        INSERT INTO Doctor
        (Name, Specialization, Hospital_name, City, State, NMR_ID, Mobile, Email)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        name, specialization, hospital_name, city, state, nmr_id, mobile, email
    ))

    doctor_id = cursor.lastrowid
    doctor_custom_id = make_doctor_id(name, specialization, doctor_id)

    cursor.execute("""
        UPDATE Doctor
        SET Doctor_Custom_ID = ?
        WHERE DOCTOR_ID = ?
    """, (doctor_custom_id, doctor_id))

    conn.commit()
    conn.close()

    return render_template(
        "index.html",
        page="doctor",
        message="Doctor registered successfully.",
        generated_id=doctor_custom_id
    )

@app.route("/appointment")
def appointment():
    return render_template("book_appointment.html")


@app.route("/book_appointment", methods=["POST"])
def book_appointment():

    patient_id = request.form["patient_id"]
    doctor_id = request.form["doctor_id"]
    date = request.form["date"]
    time = request.form["time"]

    conn = get_connection()
    cursor = conn.cursor()

    cursor.execute("""
    INSERT INTO Appointment
    (
        Patient_Custom_ID,
        Doctor_Custom_ID,
        Appointment_Date,
        Appointment_Time,
        Status
    )
    VALUES (?, ?, ?, ?, ?)
    """, (
        patient_id,
        doctor_id,
        date,
        time,
        "Booked"
    ))

    conn.commit()
    conn.close()

    return "Appointment Booked Successfully"

if __name__ == "__main__":
    create_tables()
    app.run(debug=True, use_reloader=False, port=8000)
