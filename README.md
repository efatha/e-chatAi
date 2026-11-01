# e-Chat
## e-Chat: An Advanced AI Chatbot by Efatha Rutakaza

# Overview
e-Chat is an advanced artificial intelligence chatbot, meticulously designed and developed by Efatha Rutakaza. Tailored to provide innovative solutions for a wide range of research requirements, e-Chat leverages cutting-edge AI technologies to deliver dynamic, context-aware, and highly accurate interactions. From academic inquiries to technical problem-solving and general knowledge exploration, e-Chat ensures reliable and precise responses, making it a versatile tool for diverse users.

This AI-driven platform addresses complex research challenges with unmatched efficiency and precision. Developed by Efatha Rutakaza, e-Chat exemplifies the transformative potential of artificial intelligence in revolutionizing research methodologies and enhancing problem-solving capabilities across various domains.

## Key Feature: Access Form
Before engaging with e-Chat, users will be required to complete a brief Access Form. This ensures a personalized and secure experience tailored to their specific research needs. The form collects the following details:

Name: To personalize interactions.
Email Address: For communication and support.
Purpose of Use: Academic, technical, or general research.
Preferred Language: For multilingual support.
Once the form is submitted, users will be directed to the interactive AI platform, where they can access e-Chat’s full capabilities.

## Key Features
Custom-Built AI Model: e-Chat leverages powerful machine learning frameworks to provide human-like conversational experiences.
Advanced Research Capabilities: Optimized to assist users in academic, scientific, and technical research, offering in-depth analysis and resourceful insights.
Natural Language Understanding: Supports a wide range of languages, enabling seamless communication and understanding of complex queries.
Extensibility: Open to integration with external APIs, databases, and research tools to enhance its capabilities.
User-Friendly Interface: Designed for accessibility, with features that cater to both novice and advanced users.
 ## Features
Human-like Interaction
Support for Advanced Research
Multilingual Capabilities
Extensible and Scalable
## Technology Stack
- **Python 3.11** — application runtime (`runtime.txt`).
- **Flask 3** — pages, access form, and the `/ask` chat route. **Gunicorn** serves the same app in deployment.
- **HTML, CSS, and vanilla JavaScript** — access form and chat page. No frontend framework.
- **SQLite** — conversation memory on this machine (`e_chat_memory.sqlite3`).
- **Local PDFs** — reasoning books read with **pypdf**. The PDF files stay on the machine and are not committed. **SymPy** covers extra math.
- **Wikipedia** — definitions and reflective questions, through the Wikipedia REST API and `wikipedia-api`.
- **python-dotenv** — local settings. **Flask-CORS** — only if the page is hosted apart from Flask.
- **Ollama** — optional. Used only when a local Ollama server is already running.