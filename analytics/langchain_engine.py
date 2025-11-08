import os
from langchain_openai import ChatOpenAI
from langchain_community.utilities import SQLDatabase
from langchain.chains import SQLDatabaseSequentialChain

DB_URL = os.getenv("DATABASE_URL")  # from Railway env
db = SQLDatabase.from_uri(DB_URL)

llm = ChatOpenAI(model="gpt-4-turbo", temperature=0)
analytics_chain = SQLDatabaseSequentialChain.from_llm(llm, db, verbose=True)
