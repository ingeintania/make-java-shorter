# Make Java Shorter

An experimental tool for transforming Java code into progressively more compact representations while preserving its behavior.

This project explores the idea of **code structure cost in LLM understanding**.
---

## Idea

We transform Java code through multiple levels of simplification:

L0: Original Java Code

L1: Formatting removed (whitespace, new lines, indentation)

L2: Rename variables


Each level reduces code length and potentially token usage, while studying its impact on readability and structure.

---

## ⚙️ Features

- Remove formatting (whitespace, indentation, new lines)
- Rename variables to shorter identifiers
- Generate progressively shorter Java code versions

---

## 🚀 How to Run

Run the main script:

```bash
pip install tree-sitter tree-sitter-java
python main.py
