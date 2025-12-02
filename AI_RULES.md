# AI CODING STANDARDS & BEHAVIOR

## 1. ABSOLUTE OUTPUT FORMAT
* **FULL FILES ONLY:** When asked to modify, create, or fix a file, you must output the **ENTIRE** file content from the very first import to the very last line.
* **NO TRUNCATION:** Never shorten the output. Do not stop halfway. If the response length limit is hit, stop explicitly and ask to continue in the next message.
* **NO PLACEHOLDERS:** The use of `...`, `# ... existing code ...`, `# ... rest of file ...`, or similar placeholders is **STRICTLY FORBIDDEN**. You must rewrite every single line of code, even if it hasn't changed.

## 2. CODE FORMATTING
* **STRICT LINE BREAKS:** Do not squash multiple statements onto a single line. Each import and each statement must be on its own line.
* **PEP 8 COMPLIANCE:** Follow standard Python indentation (4 spaces) and formatting rules.
* **READABILITY:** The output must be clean, readable, and identical in structure to a professional source file.

## 3. INTERACTION STYLE
* **COPY-PASTE READY:** Your output is intended to be copied directly into an IDE. It must be a single, complete, valid code block.
* **VERBOSITY:** Prioritize completeness over conciseness in code blocks.

## 4. SYNTAX & WHITESPACE INTEGRITY (CRITICAL)
* **ONE STATEMENT PER LINE:** It is STRICTLY FORBIDDEN to combine multiple statements onto a single line. 
    * **BAD:** `import time import uuid from stuff import thing`
    * **GOOD:** ```python
      import time
      import uuid
      from stuff import thing
      ```
* **DECORATORS:** Decorators (e.g., `@VerbRegistry`) must **ALWAYS** be on their own line, preceding the function or class. Never squash them into the definition line.
* **NO MINIFICATION:** Do not remove vertical whitespace to save space. Output standard, PEP 8 compliant Python code with proper newlines between classes, methods, and imports.