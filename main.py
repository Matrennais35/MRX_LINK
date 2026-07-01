import connect_llm
import generate_link
import pymrx
import smart_pandas

llm = connect_llm.get_llm(model='gpt55', version="2024-06-01")
query = "What is the average between COB 2026-06-03 and 2026-05-30 for EQ PV Diff at spot -10 for US_SPX in GLEQD"
link = generate_link.get_link(llm, query)
df = pymrx.from_link(link).get_data()

answer = smart_pandas.ask(df, link["SmartDF"], llm)
print(answer)
