from langchain_community.tools import WikipediaQueryRun, DuckDuckGoSearchRun
from langchain_community.utilities import WikipediaAPIWrapper
from langchain.tools import tool, Tool
from datetime import datetime

@tool("save_text_to_file")
def save_tool(data: str, filename: str = "research_output.txt") -> str:
    """Save the final research result to a text file."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    formatted_text = f"""
--- Research Output ---
Timestamp: {timestamp}

{data}

"""

    with open(filename, "a", encoding="utf-8") as f:
        f.write(formatted_text)

    return f"Saved to {filename}"

search = DuckDuckGoSearchRun()

search_tool = Tool(
    name="search",
    func=search.run,
    description="Search the web for information"
)

api_wrapper = WikipediaAPIWrapper(
    top_k_results=1,
    doc_content_chars_max=2000
)

wiki_query = WikipediaQueryRun(api_wrapper=api_wrapper)

wiki_tool = Tool(
    name="wikipedia_search",
    func=wiki_query.run,
    description="A wrapper around Wikipedia. Useful for when you need to answer general questions about people, places, companies, facts, historical events, or other subjects. Input should be a search query."
)