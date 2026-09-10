import os
import re
from typing import Dict, List, Set
from dotenv import load_dotenv
from ingestion.schema_extractor import TableSchema, SchemaExtractor

load_dotenv()


class SchemaFilter:
    """
    Filters database schema to select only tables relevant to the user's query.
    Preserves foreign key relationships so joined tables aren't accidentally dropped.
    """

    # Common stopwords stripped from the *question* only (never from schema
    # identifiers) so they can't generate noise matches against short column
    # names like "id" or "to".
    _STOPWORDS = {
        "a", "an", "the", "of", "to", "for", "in", "on", "at", "by", "is",
        "are", "was", "were", "with", "and", "or", "which", "who", "whose",
        "show", "list", "get", "find", "give", "me", "all", "please",
    }

    # Light business-glossary expansion: maps common question words to the
    # schema tokens that actually represent them, so questions using natural
    # business language still hit the right tables/columns.
    _SYNONYMS = {
        "price": {"price", "unitprice", "cost"},
        "cost": {"price", "unitprice", "cost"},
        "revenue": {"price", "unitprice", "total", "amount"},
        "stock": {"unitsinstock", "stock", "inventory"},
        "inventory": {"unitsinstock", "stock", "inventory"},
    }

    # If the best-scoring table doesn't clear this bar, we treat the match as
    # unreliable and fall back to the full schema rather than risk sending
    # the LLM a confidently wrong (but non-empty) table selection.
    MIN_CONFIDENT_SCORE = 1.5

    def __init__(self, full_schema: Dict[str, TableSchema]):
        self.full_schema = full_schema

    def _tokenize(self, text: str) -> Set[str]:
        """
        Converts a string into normalized word tokens.

        Critically, this splits snake_case / kebab-case / camelCase
        identifiers into their component words (e.g. 'unit_price' ->
        {'unit', 'price', 'unitprice'}) so that a multi-word question like
        "what is the unit price" can match a column named 'unit_price'.
        The previous implementation used \\w+ which treats underscores as
        word characters, so 'unit_price' tokenized as a single opaque token
        and could never match against separate question words.
        """
        # Split on anything that ISN'T a letter/digit -> underscores and
        # hyphens become separators instead of being swallowed into the token.
        raw_words = re.findall(r"[A-Za-z0-9]+", text)

        tokens: Set[str] = set()
        for word in raw_words:
            word_lower = word.lower()
            tokens.add(word_lower)

            # Split camelCase / PascalCase into sub-words too, in case any
            # identifiers use that convention instead of snake_case.
            camel_parts = re.findall(r"[A-Z]?[a-z0-9]+|[A-Z]+(?![a-z])", word)
            for part in camel_parts:
                tokens.add(part.lower())

        return tokens

    def _expand_with_synonyms(self, tokens: Set[str]) -> Set[str]:
        """Adds business-glossary synonym tokens to a question's token set."""
        expanded = set(tokens)
        for tok in tokens:
            if tok in self._SYNONYMS:
                expanded.update(self._SYNONYMS[tok])
        return expanded

    def filter_schema(self, user_question: str, top_k: int = 5) -> Dict[str, TableSchema]:
        """
        Selects relevant tables based on column name & table name matches,
        and automatically includes foreign key referenced tables.
        """
        raw_question_tokens = self._tokenize(user_question)
        question_tokens = self._expand_with_synonyms(raw_question_tokens) - self._STOPWORDS

        table_scores: Dict[str, float] = {}

        for table_name, schema in self.full_schema.items():
            score = 0.0
            table_tokens = self._tokenize(table_name)

            # Score matching table names
            if table_tokens.intersection(question_tokens):
                score += 3.0

            # Score matching column names & sample values
            for col in schema.columns:
                col_tokens = self._tokenize(col.name)
                if col_tokens.intersection(question_tokens):
                    score += 1.5

                # Check sample string matches (only meaningful question
                # tokens, length > 2, to avoid noise from short words)
                for val in col.sample_values:
                    if isinstance(val, str) and any(
                        tok in val.lower() for tok in question_tokens if len(tok) > 2
                    ):
                        score += 2.0

            if score > 0:
                table_scores[table_name] = score

        # No matches at all -> fall back to full schema.
        if not table_scores:
            return self.full_schema

        # Sort tables by relevance score
        sorted_tables = sorted(table_scores.items(), key=lambda x: x[1], reverse=True)

        # If even the BEST match is below our confidence threshold, the
        # matches we have are noise (e.g. a fluke single-token hit on an
        # unrelated table). Rather than confidently hand the LLM a wrong
        # table, fall back to the full schema so it at least has everything
        # available to reason over.
        best_score = sorted_tables[0][1]
        if best_score < self.MIN_CONFIDENT_SCORE:
            return self.full_schema

        selected_table_names = {t[0] for t in sorted_tables[:top_k]}

        # Expand selected set to include foreign key dependencies (prevents broken JOINs)
        expanded_set: Set[str] = set(selected_table_names)
        for tbl in selected_table_names:
            schema = self.full_schema[tbl]
            for fk in schema.foreign_keys:
                if fk.referred_table in self.full_schema:
                    expanded_set.add(fk.referred_table)

        return {tbl: self.full_schema[tbl] for tbl in expanded_set if tbl in self.full_schema}

    def format_for_prompt(self, schema_dict: Dict[str, TableSchema]) -> str:
        """Formats filtered schema tables into a prompt-friendly block for the SQL generator."""
        return SchemaExtractor.format_schema_for_prompt(schema_dict)


# Local Verification
if __name__ == "__main__":
    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        raise ValueError("DATABASE_URL missing in .env file!")

    extractor = SchemaExtractor(DATABASE_URL)
    full_schema = extractor.extract_full_schema()

    filter_engine = SchemaFilter(full_schema)

    # Test filtering with a specific question
    test_questions = [
        "Which customers placed orders shipped via Federal Shipping?",
        "Update the unit price of 'Chai' to $50.",
        "What is the price of Chai?",
    ]

    for test_question in test_questions:
        filtered_schema = filter_engine.filter_schema(test_question, top_k=3)
        print(f"\nUser Question: '{test_question}'")
        print(f"Total Database Tables: {len(full_schema)}")
        print(f"Filtered Schema Tables: {list(filtered_schema.keys())}")