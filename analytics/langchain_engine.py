import os
import re
from langchain_openai import ChatOpenAI
from langchain_community.utilities import SQLDatabase
from langchain_experimental.sql import SQLDatabaseSequentialChain


# -----------------------------------------------------
# 🧩 Custom Safe SQLDatabase — cleans GPT output before execution
# -----------------------------------------------------
class SafeSQLDatabase(SQLDatabase):
    def run(self, command: str, fetch: str = "all", **kwargs):
        """
        Cleans GPT-generated SQL before sending it to Postgres.
        Prevents syntax errors from ```sql or other non-SQL text.
        """
        # Remove Markdown code fences like ```sql or ```
        clean_sql = re.sub(r"```sql|```", "", command, flags=re.IGNORECASE).strip()
        # Remove excessive whitespace/newlines
        clean_sql = re.sub(r"\s+", " ", clean_sql)
        return super().run(clean_sql, fetch=fetch, **kwargs)


# -----------------------------------------------------
# 🚀 Database + Model Setup
# -----------------------------------------------------
DB_URL = os.getenv("DATABASE_URL")  # Supabase/Postgres connection string
db = SafeSQLDatabase.from_uri(DB_URL)

# Use GPT-4-Turbo for SQL reasoning and narrative commentary
llm = ChatOpenAI(model="gpt-4-turbo", temperature=0)

# Create the SQL + reasoning chain
analytics_chain = SQLDatabaseSequentialChain.from_llm(
    llm=llm,
    db=db,
    verbose=True
)


# -----------------------------------------------------
# 🧩 Wrapper Function — Safe Execution
# -----------------------------------------------------
def safe_run_chain(prompt: str):
    """
    Safely executes the analytics chain:
    - Cleans invalid SQL before it reaches the DB.
    - Uses .invoke() (modern LangChain API).
    - Returns a clean, readable string result.
    """
    try:
        raw_result = analytics_chain.invoke(prompt)

        # Extract result text from dict if present
        if isinstance(raw_result, dict) and "result" in raw_result:
            result_text = raw_result["result"]
        else:
            result_text = str(raw_result)

        # Remove any stray triple backticks or code fences
        clean_result = re.sub(r"```.*?```", "", result_text, flags=re.DOTALL).strip()
        return clean_result

    except Exception as e:
        return f"Error: {str(e)}"
