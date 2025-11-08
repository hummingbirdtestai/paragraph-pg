import os
from langchain_openai import ChatOpenAI
from langchain_community.utilities.sql_database import SQLDatabase
from langchain_experimental.sql import SQLDatabaseSequentialChain  # ✅ NEW path

DB_URL = os.getenv("DATABASE_URL")  # Supabase/Postgres connection string
db = SQLDatabase.from_uri(DB_URL)

llm = ChatOpenAI(model="gpt-4-turbo", temperature=0)

analytics_chain = SQLDatabaseSequentialChain.from_llm(
    llm=llm,
    db=db,
    verbose=True
)
