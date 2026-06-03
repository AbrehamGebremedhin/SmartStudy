from pathlib import Path
from dotenv import load_dotenv
from langchain_community.document_loaders import PyPDFLoader
from langchain_ollama import OllamaEmbeddings
from langchain_text_splitters import RecursiveCharacterTextSplitter
from pymilvus import MilvusClient, DataType
import pytesseract
from pdf2image import convert_from_path

POPPLER_PATH = r"C:\poppler-24.08.0\Library\bin"
# Minimum average characters per page before we consider a PDF image-based
OCR_THRESHOLD = 200

CHUNK_SIZE = 1000
CHUNK_OVERLAP = 200
EMBEDDING_DIM = 768  # nomic-embed-text output dimension
COLLECTION_NAME = "smartstudy"

# Resource folder is at the project root
RESOURCE_DIR = Path(__file__).parent.parent.parent / "Resource"


def _unit_sort_key(stem: str) -> int:
    """Sort PDF filenames numerically (handles 'english_1' → 1, '3' → 3)."""
    try:
        return int(stem.split("_")[-1])
    except ValueError:
        return 0


class DataLoader:
    def __init__(self, milvus_uri: str = "http://localhost:19530") -> None:
        load_dotenv("config.env")
        self.embeddings = OllamaEmbeddings(
            model="nomic-embed-text",
            base_url="http://localhost:11434",
        )
        self.client = MilvusClient(uri=milvus_uri)
        self._ensure_collection()

    # ------------------------------------------------------------------
    # Collection setup
    # ------------------------------------------------------------------

    def _ensure_collection(self) -> None:
        if self.client.has_collection(COLLECTION_NAME):
            return

        schema = self.client.create_schema(auto_id=True, enable_dynamic_field=False)
        schema.add_field("id", DataType.INT64, is_primary=True)
        schema.add_field("vector", DataType.FLOAT_VECTOR, dim=EMBEDDING_DIM)
        schema.add_field("text", DataType.VARCHAR, max_length=4096)
        schema.add_field("grade", DataType.VARCHAR, max_length=16)
        schema.add_field("subject", DataType.VARCHAR, max_length=64)
        schema.add_field("unit", DataType.VARCHAR, max_length=16)
        schema.add_field("source", DataType.VARCHAR, max_length=512)

        index_params = self.client.prepare_index_params()
        index_params.add_index(
            field_name="vector",
            metric_type="COSINE",
            index_type="IVF_FLAT",
            params={"nlist": 128},
        )

        self.client.create_collection(
            collection_name=COLLECTION_NAME,
            schema=schema,
            index_params=index_params,
        )
        print(f"Created Milvus collection '{COLLECTION_NAME}'.")

    # ------------------------------------------------------------------
    # Core helpers
    # ------------------------------------------------------------------

    def _split_pdf(self, file_path: str) -> list[str]:
        loader = PyPDFLoader(file_path, extract_images=False)
        pages = loader.load()

        total_chars = sum(len(p.page_content) for p in pages)
        avg_chars = total_chars / len(pages) if pages else 0

        if avg_chars < OCR_THRESHOLD:
            print(f"    [OCR] avg {avg_chars:.0f} chars/page — using Tesseract")
            text = self._ocr_pdf(file_path)
            raw_chunks = RecursiveCharacterTextSplitter(
                chunk_size=CHUNK_SIZE,
                chunk_overlap=CHUNK_OVERLAP,
                length_function=len,
                add_start_index=True,
            ).split_text(text)
            return raw_chunks

        splitter = RecursiveCharacterTextSplitter(
            chunk_size=CHUNK_SIZE,
            chunk_overlap=CHUNK_OVERLAP,
            length_function=len,
            add_start_index=True,
        )
        return [c.page_content for c in splitter.split_documents(pages)]

    def _ocr_pdf(self, file_path: str) -> str:
        images = convert_from_path(file_path, dpi=300, poppler_path=POPPLER_PATH)
        pages_text = [pytesseract.image_to_string(img) for img in images]
        return "\n\n".join(pages_text)

    def _insert_chunks(
        self,
        chunks: list[str],
        subject: str,
        source: str,
        grade: str = "",
        unit: str = "",
    ) -> None:
        if not chunks:
            return
        vectors = self.embeddings.embed_documents(chunks)
        data = [
            {
                "vector": vec,
                "text": text,
                "grade": grade,
                "subject": subject,
                "unit": unit,
                "source": source,
            }
            for text, vec in zip(chunks, vectors)
        ]
        self.client.insert(collection_name=COLLECTION_NAME, data=data)
        label = f"subject={subject}"
        if grade:
            label += f", grade={grade}"
        if unit:
            label += f", unit={unit}"
        print(f"  Inserted {len(data)} chunks — {label}")

    # ------------------------------------------------------------------
    # Bulk loaders
    # ------------------------------------------------------------------

    def load_all(self) -> None:
        """Walk the entire Resource directory and load every PDF into Milvus."""
        for item in sorted(RESOURCE_DIR.iterdir()):
            if not item.is_dir():
                continue
            if item.name.startswith("Grade-"):
                grade = item.name.split("-", 1)[1]  # "9", "10", "11", "12"
                self._load_grade(item, grade)
            elif item.name.lower() == "english":
                self._load_supplemental_english(item)
            elif item.name.upper() == "SAT":
                self._load_sat(item)

    def _load_grade(self, grade_dir: Path, grade: str) -> None:
        for subject_dir in sorted(grade_dir.iterdir()):
            if not subject_dir.is_dir():
                continue
            subject = subject_dir.name.lower()
            pdfs = sorted(subject_dir.glob("*.pdf"), key=lambda p: _unit_sort_key(p.stem))
            for pdf in pdfs:
                unit = pdf.stem.split("_")[-1] if "_" in pdf.stem else pdf.stem
                print(f"Loading Grade-{grade} / {subject} / Unit-{unit} ...")
                chunks = self._split_pdf(str(pdf))
                self._insert_chunks(chunks, grade=grade, subject=subject, unit=unit, source=str(pdf))

    def _load_supplemental_english(self, english_dir: Path) -> None:
        """Root-level english/ folder — cross-grade supplement, no grade or unit metadata."""
        pdfs = sorted(english_dir.glob("*.pdf"), key=lambda p: _unit_sort_key(p.stem))
        for pdf in pdfs:
            print(f"Loading english (supplemental) / {pdf.name} ...")
            chunks = self._split_pdf(str(pdf))
            self._insert_chunks(chunks, subject="english", source=str(pdf))

    def _load_sat(self, sat_dir: Path) -> None:
        """SAT folder — cross-grade supplement, no grade or unit metadata."""
        pdfs = sorted(sat_dir.glob("*.pdf"), key=lambda p: _unit_sort_key(p.stem))
        for pdf in pdfs:
            print(f"Loading SAT / {pdf.name} ...")
            chunks = self._split_pdf(str(pdf))
            self._insert_chunks(chunks, subject="sat", source=str(pdf))

    # ------------------------------------------------------------------
    # Single-file loader (for targeted re-ingestion)
    # ------------------------------------------------------------------

    def load_single(self, file_path: str, subject: str, grade: str = "", unit: str = "") -> None:
        print(f"Loading {file_path} ...")
        chunks = self._split_pdf(file_path)
        self._insert_chunks(chunks, subject=subject, source=file_path, grade=grade, unit=unit)
