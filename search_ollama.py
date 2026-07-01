import requests
import subprocess
from urllib.parse import quote_plus
""" 
Start searxng in a docker container:
# Create directories for configuration and persistent data
$ mkdir -p ./searxng/config/ ./searxng/data/
$ cd ./searxng/

# Run the container
$ docker run --name searxng -d \
    -p 8888:8080 \
    -v "./config/:/etc/searxng/" \
    -v "./data/:/var/cache/searxng/" \
    docker.io/searxng/searxng:latest

---
add in the configuration file (./searxng/config/settings.yml) the following lines:
formats:
  - html
  - json <-----

---

docker restart searxng
"""

SEARXNG_URL = "http://127.0.0.1:8888/search"
MAX_SOURCES = 50

def searxng_search(query):
    encoded = quote_plus(query)
    url = f"{SEARXNG_URL}?q={encoded}&format=json&engines=all"
    r = requests.get(url)
    r.raise_for_status()
    return r.json()

def ollama_generate(prompt):
    result = subprocess.run(
        ["ollama", "run", "sushicodechef/gemma4:12b-thinking"],
        input=prompt.encode(),
        stdout=subprocess.PIPE
    )
    return result.stdout.decode()

# query = input("Domanda: ")
query = input("Question: ")

results = searxng_search(query)

sources = "\n".join([f"- {r['url']}" for r in results["results"][:MAX_SOURCES]])

# print("Fonti trovate:")
print("Sources found:")
print(sources)

# prompt = f"""
# Rispondi alla domanda usando SOLO queste fonti:

# {sources}

# Domanda: {query}
# """
prompt = f"""Answer the question using ONLY these sources:

{sources}

Question: {query}
"""

print(ollama_generate(prompt))
