from pathlib import Path
import re

from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Install MySQL stored procedures from sql/procedures_cleaned.sql"

    def handle(self, *args, **options):
        project_dir = Path(__file__).resolve().parents[3]
        sql_file = project_dir / "sql" / "procedures_cleaned.sql"

        if not sql_file.exists():
            self.stdout.write(self.style.ERROR(f"SQL file not found: {sql_file}"))
            return

        sql_text = sql_file.read_text(encoding="utf-8-sig")
        statements = self._parse_mysql_script(sql_text)

        executable = []
        for stmt in statements:
            stmt = self._normalize_statement(stmt)
            if stmt:
                executable.append(stmt)

        if not executable:
            self.stdout.write(self.style.ERROR("No executable SQL statements found."))
            return

        self.stdout.write(self.style.WARNING(f"Executing {len(executable)} SQL statement(s)..."))

        with connection.cursor() as cursor:
            for idx, statement in enumerate(executable, start=1):
                preview = statement.strip().splitlines()[0][:120]
                self.stdout.write(f"[{idx}/{len(executable)}] {preview}")

                try:
                    cursor.execute(statement)
                except Exception as e:
                    self.stdout.write(self.style.ERROR(f"Failed on statement #{idx}"))
                    self.stdout.write(self.style.ERROR(str(e)))
                    self.stdout.write(self.style.ERROR("---- FAILED SQL START ----"))
                    self.stdout.write(statement[:4000])
                    self.stdout.write(self.style.ERROR("---- FAILED SQL END ----"))
                    raise

        self.stdout.write(self.style.SUCCESS("Stored procedures installed successfully."))

    def _parse_mysql_script(self, sql_text: str):
        statements = []
        buffer = []
        delimiter = ";"

        for raw_line in sql_text.splitlines():
            line = raw_line.rstrip()
            stripped = line.strip()

            if stripped.upper().startswith("DELIMITER "):
                pending = "\n".join(buffer).strip()
                if pending:
                    if pending.endswith(delimiter):
                        pending = pending[:-len(delimiter)].rstrip()
                    if pending:
                        statements.append(pending)
                buffer = []
                delimiter = stripped.split(None, 1)[1]
                continue

            buffer.append(line)
            joined = "\n".join(buffer).rstrip()

            if joined.endswith(delimiter):
                stmt = joined[:-len(delimiter)].rstrip()
                if stmt:
                    statements.append(stmt)
                buffer = []

        remainder = "\n".join(buffer).strip()
        if remainder:
            statements.append(remainder)

        return statements

    def _normalize_statement(self, stmt: str):
        stmt = stmt.strip()
        if not stmt:
            return None

        lines = []
        for line in stmt.splitlines():
            stripped = line.strip()
            if stripped.startswith("--") or stripped.startswith("#"):
                continue
            lines.append(line)

        stmt = "\n".join(lines).strip()
        if not stmt:
            return None

        # Remove DEFINER but keep the rest of the procedure intact
        stmt = re.sub(
            r"CREATE\s+DEFINER=`[^`]+`@`[^`]+`\s+PROCEDURE",
            "CREATE PROCEDURE",
            stmt,
            flags=re.IGNORECASE,
        )

        # Remove only MySQL versioned comment wrappers like /*!50003 ... */
        stmt = re.sub(r"/\*![0-9]{5}\s*(.*?)\*/", r"\1", stmt, flags=re.DOTALL)

        return stmt.strip()