import os
import re
import requests
import msal
from datetime import datetime, timezone
from dotenv import load_dotenv
from llm_client import chat_with_fallback

load_dotenv("/opt/clawbot/app/.env")

AZURE_CLIENT_ID = os.getenv("AZURE_CLIENT_ID")
AZURE_TENANT_ID = os.getenv("AZURE_TENANT_ID")
AZURE_CLIENT_SECRET = os.getenv("AZURE_CLIENT_SECRET")
MS_USER_EMAIL = os.getenv("MS_USER_EMAIL", "nfisher@peak10group.com")
AUDIT_LOG = "/opt/clawbot/logs/audit.log"

def audit(level, script, message):
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    line = f"{ts} | {level} | {script} | {message}\n"
    try:
        with open(AUDIT_LOG, "a") as f:
            f.write(line)
    except Exception:
        pass

def get_graph_token():
    app = msal.ConfidentialClientApplication(
        AZURE_CLIENT_ID,
        authority="https://login.microsoftonline.com/" + AZURE_TENANT_ID,
        client_credential=AZURE_CLIENT_SECRET
    )
    result = app.acquire_token_for_client(scopes=["https://graph.microsoft.com/.default"])
    return result.get("access_token")

# ── Email Agent ───────────────────────────────────────────────────────────────
def email_agent(query):
    audit("INFO", "email-agent", f"Query: {query[:50]}")
    token = get_graph_token()
    headers = {"Authorization": "Bearer " + token}
    url = ("https://graph.microsoft.com/v1.0/users/" + MS_USER_EMAIL +
           "/messages?$top=5&$select=subject,from,receivedDateTime,bodyPreview")
    emails = requests.get(url, headers=headers).json().get("value", [])
    email_context = ""
    for e in emails:
        email_context += (f"FROM: {e['from']['emailAddress']['address']}\n"
                         f"SUBJECT: {e['subject']}\n"
                         f"DATE: {e['receivedDateTime']}\n"
                         f"PREVIEW: {e['bodyPreview'][:200]}\n---\n")
    messages = [
        {"role": "system", "content": ("You are an email assistant for Nathan Fisher at Peak 10 Group. " + get_shared_memory() + "\n\n"
                                        "Answer questions about emails concisely. "
                                        "Recent emails:\n\n" + email_context)},
        {"role": "user", "content": query}
    ]
    result = chat_with_fallback(messages)
    audit("SUCCESS", "email-agent", "Response generated")
    return result

# ── Calendar Agent ────────────────────────────────────────────────────────────
def calendar_agent(query):
    audit("INFO", "calendar-agent", f"Query: {query[:50]}")
    token = get_graph_token()
    headers = {"Authorization": "Bearer " + token}
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    url = ("https://graph.microsoft.com/v1.0/users/" + MS_USER_EMAIL +
           "/calendarView?startDateTime=" + now +
           "&endDateTime=2026-03-31T00:00:00Z"
           "&$select=subject,start,end,location,organizer&$top=10"
           "&$orderby=start/dateTime")
    events = requests.get(url, headers=headers).json().get("value", [])
    cal_context = ""
    for e in events:
        start = e.get("start", {}).get("dateTime", "")[:16].replace("T", " ")
        end = e.get("end", {}).get("dateTime", "")[:16].replace("T", " ")
        cal_context += (f"MEETING: {e.get('subject', 'No title')}\n"
                       f"START: {start} END: {end}\n"
                       f"LOCATION: {e.get('location', {}).get('displayName', '')}\n---\n")
    messages = [
        {"role": "system", "content": ("You are a calendar assistant for Nathan Fisher. " + get_shared_memory() + "\n\n"
                                        "Help with scheduling, meetings, and calendar questions. "
                                        "Upcoming events:\n\n" + cal_context)},
        {"role": "user", "content": query}
    ]
    result = chat_with_fallback(messages)
    audit("SUCCESS", "calendar-agent", "Response generated")
    return result

# ── Research Agent ────────────────────────────────────────────────────────────
def research_agent(query):
    audit("INFO", "research-agent", f"Query: {query[:50]}")
    from tavily import TavilyClient
    tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))
    results = tavily.search(query + " Columbus Ohio")
    web_context = ""
    for r in results.get("results", [])[:4]:
        web_context += f"SOURCE: {r['url']}\n{r['content']}\n---\n"
    messages = [
        {"role": "system", "content": ("You are a research assistant for Nathan Fisher. " + get_shared_memory() + "\n\n"
                                        "Summarize findings clearly and concisely. "
                                        "Default location is Columbus, Ohio. "
                                        "Web search results:\n\n" + web_context)},
        {"role": "user", "content": query}
    ]
    result = chat_with_fallback(messages)
    audit("SUCCESS", "research-agent", "Response generated")
    return result

# ── Brain Agent ───────────────────────────────────────────────────────────────
def brain_agent(query):
    audit("INFO", "brain-agent", f"Query: {query[:50]}")
    import chromadb
    from chromadb.config import Settings
    from openai import OpenAI
    client_oai = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    chroma = chromadb.PersistentClient(
        path="/opt/clawbot/chroma_db",
        settings=Settings(anonymized_telemetry=False)
    )
    collection = chroma.get_or_create_collection("nate_brain")
    embedding = client_oai.embeddings.create(
        model=os.getenv("EMBED_MODEL", "text-embedding-3-small"),
        input=query
    ).data[0].embedding
    results = collection.query(query_embeddings=[embedding], n_results=5,
                               include=["documents", "metadatas"])
    brain_context = ""
    for doc, meta in zip(results["documents"][0], results["metadatas"][0]):
        brain_context += f"FILE: {meta.get('source', 'unknown')}\n{doc}\n---\n"
    messages = [
        {"role": "system", "content": ("You are a knowledge assistant for Nathan Fisher. " + get_shared_memory() + "\n\n"
                                        "Answer based only on the knowledge base provided. "
                                        "If the answer is not in the knowledge base, say so. "
                                        "Knowledge base:\n\n" + brain_context)},
        {"role": "user", "content": query}
    ]
    result = chat_with_fallback(messages)
    audit("SUCCESS", "brain-agent", "Response generated")
    return result

# ── AgentMail Send Agent ──────────────────────────────────────────────────────
def agentmail_send_agent(query):
    """
    Parse a natural-language 'send email to X about Y' query, compose the
    message with GPT, and deliver it via ClawBot's AgentMail inbox.

    ClawBot's @agentmail.to address is used for all agent-originated outbound
    mail.  Nate's Outlook inbox is never touched for sending here.
    """
    audit("INFO", "agentmail-send", f"Query: {query[:80]}")

    # ── Extract recipient from query ──────────────────────────────────────────
    # Patterns: "email john@x.com about ...", "send to foo@bar.com re ..."
    email_match = re.search(
        r'(?:to|email|send to)\s+([\w.+-]+@[\w.-]+\.[a-zA-Z]{2,})',
        query, re.IGNORECASE
    )
    recipient = email_match.group(1) if email_match else None

    if not recipient:
        audit("WARN", "agentmail-send", "No recipient found in query")
        return ("I couldn't find a recipient email address in your request. "
                "Please include the address, e.g. 'send email to person@example.com about …'")

    # ── Compose subject & body via LLM ────────────────────────────────────────
    compose_prompt = (
        "You are ClawBot, the AI Chief of Staff for Nathan Fisher at Peak 10 Group. "
        "Draft a short, professional email based on this instruction:\n\n"
        f"{query}\n\n"
        "Reply in JSON with exactly two keys: \"subject\" (string) and \"body\" (string, plain text). "
        "Do NOT include a signature in the body."
    )
    raw = chat_with_fallback([{"role": "user", "content": compose_prompt}])

    # Parse JSON from LLM response
    try:
        import json
        json_match = re.search(r'\{.*\}', raw, re.DOTALL)
        parsed = json.loads(json_match.group(0)) if json_match else {}
        subject = parsed.get("subject", "Message from ClawBot")
        body = parsed.get("body", raw)
    except Exception:
        subject = "Message from ClawBot"
        body = raw

    # Append signature
    signature = "\n\nSent via ClawBot on behalf of Nathan D. Fisher\nPeak 10 Group | www.peak10group.com"
    full_body = body + signature

    # ── Send via AgentMail ────────────────────────────────────────────────────
    try:
        from agentmail_client import send_email, get_agent_inbox_id
        send_email(to=recipient, subject=subject, text=full_body, labels=["clawbot-sent"])
        agent_inbox = get_agent_inbox_id()
        audit("SUCCESS", "agentmail-send", f"Sent to {recipient}: {subject}")
        return (f"Email sent to **{recipient}** via ClawBot's agent inbox ({agent_inbox}).\n"
                f"**Subject:** {subject}")
    except Exception as e:
        audit("ERROR", "agentmail-send", f"Send failed: {e}")
        return f"Failed to send email: {e}"


# ── AgentMail Inbox Agent ─────────────────────────────────────────────────────
def agentmail_inbox_agent(query):
    """List or read messages received in ClawBot's own @agentmail.to inbox."""
    audit("INFO", "agentmail-inbox", f"Query: {query[:80]}")
    try:
        from agentmail_client import list_messages, get_agent_inbox_id
        messages = list_messages(limit=5)
        agent_inbox = get_agent_inbox_id()
        if not messages:
            return f"No messages in ClawBot's agent inbox ({agent_inbox})."
        context = f"ClawBot inbox: {agent_inbox}\n\n"
        for m in messages:
            context += (f"FROM: {m.get('from_', 'unknown')}\n"
                        f"SUBJECT: {m.get('subject', '')}\n"
                        f"DATE: {m.get('created_at', '')}\n"
                        f"BODY: {(m.get('text') or '')[:300]}\n---\n")
        chat_messages = [
            {"role": "system", "content": ("You are ClawBot. Summarise or answer questions about "
                                           "messages received in the agent inbox.\n\n" + context)},
            {"role": "user", "content": query}
        ]
        result = chat_with_fallback(chat_messages)
        audit("SUCCESS", "agentmail-inbox", "Response generated")
        return result
    except Exception as e:
        audit("ERROR", "agentmail-inbox", f"Failed: {e}")
        return f"Could not read agent inbox: {e}"


# ── Router ────────────────────────────────────────────────────────────────────
def route(query):
    q = query.lower()
    if any(k in q for k in ["cfo", "financial summary", "p&l", "profit and loss",
                              "balance sheet", "delinquency report", "quarterly report",
                              "vendor payment", "financial report", "bookkeeping",
                              "ytd financials", "fraud log", "budget", "noi",
                              "net operating income", "revenue", "expenses report"]):
        from cfo_agent import cfo_query, cfo_summary, cfo_report
        if any(k in q for k in ["summary", "overview", "snapshot"]):
            return "cfo", cfo_summary()
        if "report" in q:
            topic = query.split("report")[-1].strip() or "overall financial performance"
            return "cfo", cfo_report(topic)
        return "cfo", cfo_query(query)
    if any(k in q for k in ["sharepoint", "sp site", "sp folder", "sp search", "peak 10 main", "peak10 main"]):
        from sharepoint_agent import list_sites, list_folders, search_files as sp_search
        if any(k in q for k in ["list sites", "show sites", "all sites"]):
            return "sharepoint", list_sites()
        if any(k in q for k in ["search", "find"]):
            keyword = query.split("find")[-1].strip() if "find" in q else query.split("search")[-1].strip()
            return "sharepoint", sp_search(keyword)
        return "sharepoint", list_folders("Peak10")
    if any(k in q for k in ["onedrive", "my files", "save to", "find my file", "find files", "upload", "download file", "in onedrive", "on onedrive"]):
        from onedrive_agent import list_files, search_files
        if "search" in q or "find" in q:
            keyword = query.split("find")[-1].strip() if "find" in q else query.split("search")[-1].strip()
            return "onedrive", search_files(keyword)
        return "onedrive", list_files()
    if any(k in q for k in ["fireflies", "transcript", "meeting transcript", "meeting summary", "meeting notes"]):
        from fireflies_agent import run_transcript_pipeline
        return "fireflies", run_transcript_pipeline(5)
    if any(k in q for k in ["fathom", "fathom meeting", "fathom video", "fathom summary"]):
        from fathom_agent import get_recent_meetings, format_meetings
        meetings = get_recent_meetings(5)
        return "fathom", format_meetings(meetings)
    # Agent-originated outbound email via AgentMail (ClawBot's own inbox)
    if any(k in q for k in ["send email to", "send a message to", "send an email to",
                              "email to ", "draft and send", "compose and send"]):
        return "agentmail-send", agentmail_send_agent(query)
    # Check ClawBot's own AgentMail inbox
    if any(k in q for k in ["agent inbox", "clawbot inbox", "agentmail inbox",
                              "replies to clawbot", "messages for clawbot"]):
        return "agentmail-inbox", agentmail_inbox_agent(query)
    if any(k in q for k in ["email", "inbox", "message from", "did i get", "unread", "mail"]):
        return "email", email_agent(query)
    elif any(k in q for k in ["calendar", "schedule", "meeting", "appointment", "agenda", "when is my"]):
        return "calendar", calendar_agent(query)
    elif any(k in q for k in ["today", "current", "latest", "news", "price", "weather", "search", "find me", "look up"]):
        return "research", research_agent(query)
    else:
        return "brain", brain_agent(query)
