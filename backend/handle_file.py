import os
import re
import traceback


class FileHandler:
    """Routes text-based file types (pdf, docx, txt) through extraction and AI processing."""

    def __init__(self, ai_model=None):
        """Initialize with an optional Baymax AI model instance."""
        self.ai_model = ai_model

    def process_file(self, file_path: str, user_query: str) -> str:
        """Main pipeline: detect type → extract → clean → NLP → model."""
        try:
            if not os.path.exists(file_path):
                return "Error: File does not exist."

            file_type = self._get_file_type(file_path)
            if not file_type:
                return "Error: Unsupported file format. Only PDF, DOCX, DOC, and TXT are supported."

            raw_text = self._extract_text(file_path, file_type)
            if not raw_text or not raw_text.strip():
                return "Error: Could not extract readable text from the file."

            cleaned_text = self._clean_text(raw_text)

            from backend.Nlp import preprocess
            nlp_result = preprocess(user_query, source="file_handle")
            intent = nlp_result.get("intent", "file_analysis")

            return self._route_to_model(cleaned_text, user_query, intent)

        except Exception as e:
            traceback.print_exc()
            return f"Error during file processing: {str(e)}"

    def _get_file_type(self, file_path: str) -> str:
        """Detect file type based on extension; returns None for unsupported types."""
        ext = os.path.splitext(file_path)[1].lower()
        supported = {
            ".pdf":  "pdf",
            ".doc":  "docx",
            ".docx": "docx",
            ".txt":  "txt",
        }
        return supported.get(ext, None)

    def _extract_text(self, file_path: str, file_type: str) -> str:
        """Route to the appropriate extractor based on file type."""
        if file_type == "pdf":
            return self._read_pdf(file_path)
        elif file_type == "docx":
            return self._read_docx(file_path)
        elif file_type == "txt":
            return self._read_txt(file_path)
        return ""

    def _read_pdf(self, file_path: str) -> str:
        """Extract text from a PDF using pdfplumber."""
        text_content = []
        try:
            import pdfplumber
            with pdfplumber.open(file_path) as pdf:
                for page in pdf.pages:
                    extracted = page.extract_text()
                    if extracted:
                        text_content.append(extracted)
        except ImportError:
            return "Error: pdfplumber is not installed. Please install it via pip."
        except Exception as e:
            print(f"Error reading PDF: {e}")
        return "\n".join(text_content)

    def _read_docx(self, file_path: str) -> str:
        """Extract text from a DOCX/DOC file using python-docx."""
        text_content = []
        try:
            import docx
            doc = docx.Document(file_path)
            for para in doc.paragraphs:
                text_content.append(para.text)
        except ImportError:
            return "Error: python-docx is not installed. Please install it via pip."
        except Exception as e:
            print(f"Error reading DOC/DOCX: {e}")
        return "\n".join(text_content)

    def _read_txt(self, file_path: str) -> str:
        """Read a plain text file with UTF-8 and ISO-8859-1 fallback."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                return f.read()
        except UnicodeDecodeError:
            try:
                with open(file_path, "r", encoding="iso-8859-1") as f:
                    return f.read()
            except Exception as e:
                print(f"Error reading TXT: {e}")
        except Exception as e:
            print(f"Error reading TXT: {e}")
        return ""

    def _clean_text(self, text: str) -> str:
        """Remove excess whitespace, noise characters, and consecutive blank lines."""
        if not text:
            return ""
        cleaned = re.sub(r'\n{3,}', '\n\n', text)
        cleaned = re.sub(r'[ \t]+', ' ', cleaned)
        cleaned = re.sub(r'[^\w\s\-\.,?!:;\'"()\[\]{}@*#%/+=\\]', '', cleaned)
        return cleaned.strip()

    def _route_to_model(self, file_content: str, user_query: str, intent: str) -> str:
        """Format the extracted content and send it to the AI model for analysis."""
        if not self.ai_model:
            return "Error: No AI model provided to process the extracted text."

        combined_prompt = (
            f"Here is the content of the uploaded document:\n\n"
            f"--- DOCUMENT START ---\n"
            f"{file_content}\n"
            f"--- DOCUMENT END ---\n\n"
            f"User request: {user_query}\n\n"
            f"IMPORTANT:\n"
            f"- Give clear and useful answer\n"
            f"- Focus on user question\n"
            f"- Keep response structured\n"
            f"- Avoid unnecessary long explanation\n"
            f"- Do NOT stop early\n"
            f"- Cover ALL sections of the document\n"
            f"- Continue until full analysis is done\n"
        )

        if hasattr(self.ai_model, "handle_text"):
            return self.ai_model._with_fallback(
                self.ai_model.models["file_analysis"],
                combined_prompt,
                max_tokens=self.ai_model._TOKEN_BUDGETS["file_analysis"],
                task="file_analysis",
            )

        return "Error: The configured AI model lacks a text handling method."