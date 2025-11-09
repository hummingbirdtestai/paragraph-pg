import os
import re
from langchain_openai import ChatOpenAI
from langchain_community.utilities import SQLDatabase
from langchain_experimental.sql import SQLDatabaseSequentialChain

# -----------------------------------------------------
# 🚀 Database + Model Setup
# -----------------------------------------------------
DB_URL = os.getenv("DATABASE_URL")  # Supabase/Postgres connection string
db = SQLDatabase.from_uri(DB_URL)

# Use GPT-4 Turbo for accurate SQL + commentary generation
llm = ChatOpenAI(model="gpt-4-turbo", temperature=0)

# Create the SQL reasoning chain
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
    - Removes ```sql fences from GPT output.
    - Uses .invoke() instead of deprecated .run().
    - Returns clean text result.
    """
    try:
        raw_result = analytics_chain.invoke(prompt)
        # Some versions of LangChain return dicts, others return str
        if isinstance(raw_result, dict) and "result" in raw_result:
            result_text = raw_result["result"]
        else:
            result_text = str(raw_result)

        # Remove accidental Markdown code fences or triple backticks
        clean_result = re.sub(r"```.*?```", "", result_text, flags=re.DOTALL).strip()
        return clean_result

    except Exception as e:
        return f"Error: {str(e)}"
