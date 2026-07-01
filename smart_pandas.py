"""
SmartPandas — answer natural-language questions over a pymrx dataframe.

Wraps the existing LangChain chat model (see connect_llm.py) so pandasai
can drive it, then delegates the actual Q&A to pandasai's Agent, which
writes and executes pandas code against the dataframe.
"""

import pandas as pd
import pandasai as pai
from pandasai.llm.base import LLM as PandasAILLM

from pipeline_errors import AnswerError


class LangchainLLM(PandasAILLM):
    """Adapts a LangChain chat model to pandasai's LLM interface."""

    def __init__(self, llm):
        super().__init__()
        self._llm = llm

    def call(self, instruction, context=None) -> str:
        response = self._llm.invoke(instruction.to_string())
        return response.content

    @property
    def type(self) -> str:
        return "langchain"


def ask(df: pd.DataFrame, question: str, llm) -> str:
    """Answer a natural-language question about `df` using `llm`."""
    smart_df = pai.DataFrame(df)
    pai.config.set({"llm": LangchainLLM(llm)})
    try:
        return smart_df.chat(question)
    except Exception as e:
        raise AnswerError(f"Failed to answer question over the data: {e}") from e
