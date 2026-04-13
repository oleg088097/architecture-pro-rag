import logging
import os
from pathlib import Path
from telegram import Update
from telegram.ext import ApplicationBuilder, ContextTypes, CommandHandler, MessageHandler, filters
from langchain_chroma import Chroma
from langchain_huggingface import HuggingFaceEmbeddings
from langchain.agents import AgentState, create_agent
from langchain.agents.middleware import before_model, after_model
from langchain_core.vectorstores import VectorStoreRetriever
from langchain.chat_models import init_chat_model


class State(AgentState):
    input: str
    answer: str
    context: list

ROOT = Path(__file__).resolve().parent
DEFAULT_CHROMA_DIR = ROOT.parent / "task3" / "chroma_data"
COLLECTION_NAME = "pokemon_kb"
EMBEDDING_MODEL_ID = "BAAI/bge-m3"

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
top_k=5
embeddings = HuggingFaceEmbeddings(model_name=EMBEDDING_MODEL_ID)
vector_store = Chroma(
    collection_name=COLLECTION_NAME,
    embedding_function=embeddings,
    persist_directory=DEFAULT_CHROMA_DIR,
)
retriever = VectorStoreRetriever(vectorstore=vector_store)
model = init_chat_model("openrouter:qwen3.6-plus:free")

@before_model
def get_context(state, runtime):
    retrieved_docs = retriever.invoke(state["input"])
    context = "\n\n".join([doc.page_content for doc in retrieved_docs])
    system_prompt = (
        "You are a helper who thinks first and then responds. Always write down your steps. Wrap those steps with <thinking></thinking> "
        "Use the given context to answer the question. "
        "If you don't know the answer, say you don't know. "
        "For answers use three sentence maximum and keep it concise. "
        "Example 1:"
        "Q: What type is Pyrothyr?"
        "A: <thinking>1. Examining the documents for Pyrothyr. 2. Documents state that Pyrothyr are Fire/Flying-type. 3. Answer - Fire/Flying-type.</thinking>Pyrothyr is Fire/Flying-type Vesperkin. "
        "Example 2:"
        "Q: Who are the members of Eclipse Syndicate trio?"
        "A: <thinking>1. Examining the documents for Eclipse Syndicate trio. 2. Documents state that Eclipse Syndicate trio is a most recurring members of Eclipse Syndicate and consist of Sera Kael, Theo Maris and Whiskalk. 3. Answer - Sera Kael, Theo Maris and Whiskalk.</thinking>Eclipse Syndicate trio members are Sera Kael, Theo Maris and Whiskalk"
        f"Context: {context}"
    )
    messages = [
        ("system", system_prompt),
        ("human", state["input"])
    ]
    return {"context": retrieved_docs, "messages": messages}

@after_model
def get_answer(state, runtime):
    return {"answer": state["messages"][-1].content}

agent = create_agent(model=model, middleware=[get_context, get_answer], state_schema=State)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await context.bot.send_message(chat_id=update.effective_chat.id, text="Ask questions for knowledge base")

async def question(update: Update, context: ContextTypes.DEFAULT_TYPE):
    response = agent.invoke({"input": update.message.text})
    answer = response["messages"][-1].content
    print(answer)
    await context.bot.send_message(chat_id=update.effective_chat.id, text=answer)
    #await context.bot.send_message(chat_id=update.effective_chat.id, text=update.message.text)

if __name__ == '__main__':
    application = ApplicationBuilder().token(os.environ["TG_BOT_TOKEN"]).build()
    
    start_handler = CommandHandler('start', start)
    application.add_handler(start_handler)

    echo_handler = MessageHandler(filters.TEXT & (~filters.COMMAND), question)
    application.add_handler(echo_handler)

    application.run_polling()