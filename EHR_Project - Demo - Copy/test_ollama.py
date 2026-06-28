from dotenv import load_dotenv

from app import generate_ollama_summary, get_ollama_model


load_dotenv()

print(f"Using Ollama model: {get_ollama_model()}")
summary = generate_ollama_summary(
    "Write one short sentence summarizing: Patient has chest pain and high blood pressure."
)

print(summary)
print("Test completed successfully.")
