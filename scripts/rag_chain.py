import os
from dotenv import load_dotenv, find_dotenv
from langchain_google_genai import ChatGoogleGenerativeAI
from langchain.prompts import ChatPromptTemplate
from langchain.chains import LLMChain

load_dotenv(find_dotenv())

def get_rag_chain():
    # Configure Gemini
    llm = ChatGoogleGenerativeAI(
        model="gemini-2.5-flash",
        temperature=0,
        max_tokens=None,
        timeout=None,
        max_retries=2
    )

    # Prompt
    system_template = """
    You are a helpful Site Reliability / Systems Assistant. 
    Your task: given server log snippets and a user's query:

    1. Detect if the logs indicate an anomaly or not.
    2. If anomaly detected → classify error type, propose a fix, suggest commands.
    3. If no anomaly → state clearly "No anomaly detected."

    Return only a JSON object with keys:
    - anomaly_detected (true/false)
    - error_type (string or "none")
    - suggested_fix (string or "none")
    - commands (list of strings or [])
    - explanation (short reasoning)
    - confidence (low/medium/high)
    """

    user_template = """
    USER QUERY:
    {query}

    TOP LOG SNIPPETS:
    {context}
    """

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_template),
        ("human", user_template),
    ])

    return prompt | llm
