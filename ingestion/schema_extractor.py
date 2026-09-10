import os
import json
import hashlib
import warnings
from typing import Dict, List, Any, Optional
from pydantic import BaseModel, Field
from sqlalchemy import create_engine, inspect, MetaData, Table, select
from sqlalchemy.exc import SAWarning

# Suppress SQLAlchemy type mapping warnings (such as bpchar)
warnings.filterwarnings('ignore', category=SAWarning)


class ColumnInfo(BaseModel):
    name: str
    type: str
    is_primary_key: bool
    is_nullable: bool
    sample_values: List[Any] = Field(default_factory=list)


class ForeignKeyInfo(BaseModel):
    constrained_columns: List[str]
    referred_table: str
    referred_columns: List[str]


class TableSchema(BaseModel):
    table_name: str
    columns: List[ColumnInfo]
    foreign_keys: List[ForeignKeyInfo]
    description: Optional[str] = None


class SchemaExtractor:
    """
    Introspects a database (PostgreSQL/Supabase or SQLite) via SQLAlchemy to
    produce a structured representation of schema metadata and categorical
    sample values for LLM prompt context. Dialect-aware: Postgres tables are
    read from the "public" schema by default, SQLite is read with no schema
    (SQLite has no schema namespaces).
    Includes persistent local file caching, keyed per-database, under cache/.
    """

    def __init__(self, db_url: str, cache_file: Optional[str] = None):
        self.db_url = db_url
        self.engine = create_engine(self.db_url, pool_pre_ping=True)
        self.inspector = inspect(self.engine)

        # The dialect drives how we introspect (Postgres has schemas like
        # "public"; SQLite has no schema concept at all) and lets us pick a
        # sensible default schema_name in extract_full_schema().
        self.dialect_name = self.engine.dialect.name  # e.g. "postgresql", "sqlite"

        # Cache is keyed per-database so evaluating many different SQLite
        # files (or switching between SQLite and Supabase) never reuses a
        # stale/foreign schema from a previous database.
        if cache_file is None:
            db_fingerprint = hashlib.md5(self.db_url.encode("utf-8")).hexdigest()[:12]
            cache_file = f"cache/schema_cache_{db_fingerprint}.json"
        self.cache_file = cache_file

    def extract_table_schema(self, table_name: str, sample_limit: int = 5) -> TableSchema:
        """Extracts column details, primary keys, foreign keys, and categorical sample values for a single table."""
        
        # Primary Keys
        pk_constraint = self.inspector.get_pk_constraint(table_name)
        primary_keys = set(pk_constraint.get("constrained_columns", []))

        # Raw Column Info
        raw_columns = self.inspector.get_columns(table_name)
        columns_info = []

        with self.engine.connect() as conn:
            metadata = MetaData()
            table = Table(table_name, metadata, autoload_with=self.engine)

            for col in raw_columns:
                col_name = col["name"]
                raw_type = col.get("type")
                
                # Fix bpchar / NULL type handling for Postgres fixed-length CHAR types
                col_type = str(raw_type) if raw_type is not None else "VARCHAR"
                if "BPCHAR" in col_type.upper() or col_type == "NULL":
                    col_type = "CHAR"

                is_pk = col_name in primary_keys
                is_nullable = col.get("nullable", True)

                # Query sample distinct values for string/categorical columns
                sample_vals = []
                type_upper = col_type.upper()
                if any(t in type_upper for t in ["VARCHAR", "TEXT", "CHAR", "BPCHAR", "STRING"]):
                    try:
                        query = (
                            select(table.c[col_name])
                            .where(table.c[col_name].isnot(None))
                            .distinct()
                            .limit(sample_limit)
                        )
                        res = conn.execute(query).fetchall()
                        sample_vals = [r[0] for r in res if r[0] is not None]
                    except Exception:
                        sample_vals = []

                columns_info.append(
                    ColumnInfo(
                        name=col_name,
                        type=col_type,
                        is_primary_key=is_pk,
                        is_nullable=is_nullable,
                        sample_values=sample_vals,
                    )
                )

        # Foreign Key Relationships
        raw_fks = self.inspector.get_foreign_keys(table_name)
        fks_info = [
            ForeignKeyInfo(
                constrained_columns=fk.get("constrained_columns", []),
                referred_table=fk.get("referred_table", ""),
                referred_columns=fk.get("referred_columns", []),
            )
            for fk in raw_fks
        ]

        return TableSchema(
            table_name=table_name,
            columns=columns_info,
            foreign_keys=fks_info,
        )

    def extract_full_schema(self, schema_name: Optional[str] = None, force_refresh: bool = False) -> Dict[str, TableSchema]:
        """
        Extracts schema definitions for all non-system tables in the database.
        Reads from schema_cache.json if available unless force_refresh is True.

        `schema_name` is dialect-dependent: Postgres organizes tables under
        named schemas (defaulting to "public"), while SQLite has no schema
        concept at all and errors out if asked to look inside one (e.g.
        "public"). If the caller doesn't explicitly pass a schema_name, we
        pick a sane default from the engine's dialect.
        """
        if schema_name is None:
            if self.dialect_name == "sqlite":
                schema_name = None  # SQLite: never pass a schema
            elif self.dialect_name in ("postgresql", "postgres"):
                schema_name = "public"  # Supabase/Postgres default schema
            else:
                schema_name = None  # Safe default for any other dialect

        # Read from cache if it exists and force_refresh is False
        if not force_refresh and os.path.exists(self.cache_file):
            try:
                print(f"📦 Loading schema from local cache: {self.cache_file}")
                with open(self.cache_file, "r", encoding="utf-8") as f:
                    cached_data = json.load(f)
                
                full_schema = {}
                for tbl_name, tbl_data in cached_data.items():
                    full_schema[tbl_name] = TableSchema(**tbl_data)
                return full_schema
            except Exception as e:
                print(f"⚠️ Cache read error ({e}). Extracting live schema...")

        # Live Database Extraction
        print("🔍 Performing live schema extraction from database...")
        table_names = self.inspector.get_table_names(schema=schema_name)
        full_schema = {}
        for table in table_names:
            full_schema[table] = self.extract_table_schema(table)

        # Save to local cache
        try:
            cache_dir = os.path.dirname(self.cache_file)
            if cache_dir:
                os.makedirs(cache_dir, exist_ok=True)
            cache_payload = {tbl: schema.model_dump() for tbl, schema in full_schema.items()}
            with open(self.cache_file, "w", encoding="utf-8") as f:
                json.dump(cache_payload, f, indent=2)
            print(f"✅ Schema cached successfully to {self.cache_file}")
        except Exception as e:
            print(f"⚠️ Failed to write cache: {e}")

        return full_schema

    @staticmethod
    def format_schema_for_prompt(schema_dict: Dict[str, TableSchema]) -> str:
        """Formats the extracted schema into a structured string context for LLM prompts."""
        formatted_blocks = []
        
        for table_name, schema in schema_dict.items():
            block = [f"Table: {table_name}", "Columns:"]
            
            for col in schema.columns:
                pk_tag = " [PK]" if col.is_primary_key else ""
                sample_tag = f" | Samples: {col.sample_values}" if col.sample_values else ""
                block.append(f"  - {col.name} ({col.type}){pk_tag}{sample_tag}")

            if schema.foreign_keys:
                block.append("Foreign Keys:")
                for fk in schema.foreign_keys:
                    cols_from = ", ".join(fk.constrained_columns)
                    cols_to = ", ".join(fk.referred_columns)
                    block.append(f"  - {cols_from} -> {fk.referred_table}({cols_to})")

            formatted_blocks.append("\n".join(block))

        return "\n\n".join(formatted_blocks)


# Verification Script Execution
if __name__ == "__main__":
    DATABASE_URL = os.getenv(
        "DATABASE_URL", 
        "postgresql://postgres:Text-to-SQL@db.uczokcyixfajfrhztoxx.supabase.co:5432/postgres"
    )

    print("Connecting to database...")
    extractor = SchemaExtractor(DATABASE_URL)
    
    # Extract schema (will use cache or build cache on first run)
    schema = extractor.extract_full_schema()
    prompt_formatted_schema = extractor.format_schema_for_prompt(schema)
    
    print("\n--- EXTRACTED SCHEMA FOR LLM PROMPT ---")
    print(prompt_formatted_schema)