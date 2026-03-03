from dotenv import load_dotenv
load_dotenv()

import os
from langchain_openai import ChatOpenAI, OpenAIEmbeddings
from langchain_community.vectorstores import FAISS
from calculations import (
    calculate_pf,
    calculate_esi,
    calculate_pt,
    calculate_bonus,
    calculate_gratuity
)

# Globals (lazy-loaded)
_embeddings = None
_db = None
_llm = None

SYSTEM_PROMPT = """
You are an Indian Payroll Compliance Assistant.

Use ONLY the provided Context to explain and cite laws.

Rules:
- Use Deterministic Calculations exactly as given.
- Do NOT recalculate values.
- Do NOT mix different laws.
- Always provide short legal reference snippet.

Output format:

Answer:
Conditions:
Formula:
Calculation:
Reference:
"""


def get_engine():
    """
    Lazy-load embeddings, vectorstore, and LLM.
    Ensures vectorstore exists before loading.
    """
    global _embeddings, _db, _llm

    if _embeddings is None:
        _embeddings = OpenAIEmbeddings()

    if _db is None:
        if not os.path.exists("vectorstore/index.faiss"):
            raise RuntimeError(
                "Vectorstore not found. Ingestion may not have completed yet."
            )
        _db = FAISS.load_local(
            "vectorstore",
            _embeddings,
            allow_dangerous_deserialization=True
        )

    if _llm is None:
        _llm = ChatOpenAI(model="gpt-4.1-mini", temperature=0)

    return _db, _llm


def boost_query(question, state, basic, gross):
    q_lower = question.lower()

    retrieval_query = f"""
    {question}
    State: {state}
    Basic: {basic}
    Gross: {gross}
    """

    if "pf" in q_lower or "epf" in q_lower:
        retrieval_query += "Include wage ceiling 15000, contribution rate 12%, EPS 8.33%."

    if "esi" in q_lower:
        retrieval_query += "Include eligibility threshold 21000, contribution rates."

    if "bonus" in q_lower:
        retrieval_query += "Include eligibility salary limit 21000, minimum 8.33%, maximum 20%."

    if "gratuity" in q_lower:
        retrieval_query += "Include 5 years rule, 15/26 formula."

    return retrieval_query


def route_filter(question, state):
    q_lower = question.lower()

    if "pf" in q_lower or "epf" in q_lower:
        return {"doc_name": "pf.pdf"}

    if "esi" in q_lower:
        return {"doc_name": "esi.pdf"}

    if "bonus" in q_lower:
        return {"doc_name": "bonus.pdf"}

    if "gratuity" in q_lower:
        return {"doc_name": "gratuity.pdf"}

    if "professional tax" in q_lower or "pt" in q_lower:
        if state.upper() == "KA":
            return {"doc_name": "pt_ka.pdf"}
        if state.upper() == "MH":
            return {"doc_name": "pt_mh.pdf"}

    return None


def process_query(question, state, emp_type, basic, gross, years_of_service):
    # Deterministic engine
    q_lower = question.lower()
    calculated_data = {}

    if "pf" in q_lower or "epf" in q_lower:
        calculated_data = calculate_pf(basic)
    elif "esi" in q_lower:
        calculated_data = calculate_esi(gross)
    elif "professional tax" in q_lower or "pt" in q_lower:
        calculated_data = calculate_pt(state, gross)
    elif "bonus" in q_lower:
        calculated_data = calculate_bonus(gross)
    elif "gratuity" in q_lower:
        calculated_data = calculate_gratuity(basic, years_of_service)

    # Lazy-load engine AFTER ingestion
    db, llm = get_engine()

    retrieval_query = boost_query(question, state, basic, gross)
    filter_doc = route_filter(question, state)

    if filter_doc:
        docs = db.max_marginal_relevance_search(
            retrieval_query, k=5, filter=filter_doc
        )
    else:
        docs = db.max_marginal_relevance_search(retrieval_query, k=5)

    context = "\n\n".join(
        [d.page_content for d in docs if d.page_content]
    )

    prompt = f"""
{SYSTEM_PROMPT}

Context:
{context}

User Inputs:
State: {state}
Basic: {basic}
Gross: {gross}
Years of Service: {years_of_service}

Deterministic Calculations:
{calculated_data}

Question:
{question}
"""

    response = llm.invoke(prompt)
    return response.content