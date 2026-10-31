# e-Chat
## e-Chat: An Advanced AI Chatbot by Efatha Rutakaza

# Overview
e-Chat is an in-development, locally operated assistant built with Flask and
Python. It can handle selected deterministic reasoning patterns, curated local
facts, conversation memory, and retrieval from PDFs placed in `books/`.
Its current implementation is not a general-purpose language model and does
not yet provide broad research coverage. Answer quality depends on the rules,
curated data, and books available on the machine.

## Key Feature: Access Form
The current interface includes an access form intended to personalize the
experience. It collects:

Name: To personalize interactions.
Email Address: For communication and support.
Purpose of Use: Academic, technical, or general research.
Preferred Language: For multilingual support.
Once the form is submitted, users will be directed to the interactive AI platform, where they can access e-Chat’s full capabilities.

## Key Features
- Local reasoning: deterministic Python rules for arithmetic, selected proofs, and curated facts.
- Book retrieval: indexes PDFs in `books/` locally and returns matching excerpts with title and page.
- Offline by design: chat requests do not call hosted APIs, web search, Wikipedia, or a local model server.
- Honest limits: when local evidence is not strong enough, e-Chat abstains rather than inventing a sourced answer.

The book retriever uses lexical matching and a small built-in set of concept aliases. It is not a trained language model or a general semantic search engine. New results should be covered by offline regression tests before treating them as reliable.
 ## Features
Human-like Interaction
Support for Advanced Research
Multilingual Capabilities
Extensible and Scalable
## Technology Stack
Frontend: Python, Vanilla JavaScript, HTML(Flask), CSS

## Offline reasoning and book-retrieval scorecard

Run the local reasoning regression set with:

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
```

The scorecard checks arithmetic and proof patterns, selected definitions,
unsupported-answer abstention, and local book retrieval for paraphrased questions.
Book results must retain their title and page. These tests run without external
services. Passing them verifies only the included cases; it does not measure
general knowledge or train a model.

Current acceptance targets are 100% on the included deterministic proof,
counterexample, and definition cases; no fabricated proof for a malformed or
unsupported induction claim; and no citation for a table of contents, index
entry, or unrelated passage.
