"""
Bucket X — Latin America (Spanish/Portuguese) + FSU (Russian).
Entire continents uncovered. Chabad has massive presence in Buenos Aires,
São Paulo, Mexico City, Montevideo, Santiago. Also Russia/Ukraine.
"""
import asyncio, json, hashlib, os, pathlib, httpx, random, itertools
FLEET = pathlib.Path("/Volumes/EOS_DIGITAL/llm-fleet")
for line in open(FLEET/".env"):
    line=line.strip()
    if "=" in line and not line.startswith("#"):
        k,v=line.split("=",1); os.environ.setdefault(k,v.strip('"').strip("'"))
ROOT = pathlib.Path("/Volumes/EOS_DIGITAL/chabad-tracker")
KEYS = [k.strip() for k in os.environ["TAVILY_API_KEYS"].split(",") if k.strip()]

# Spanish-language LATAM
LATAM_SITES = [
    "lanacion.com.ar", "clarin.com", "infobae.com",   # Argentina
    "perfil.com", "pagina12.com.ar",
    "folha.uol.com.br", "estadao.com.br", "oglobo.globo.com",  # Brazil
    "eluniversal.com.mx", "milenio.com", "jornada.com.mx",     # Mexico
    "elpais.com.uy", "elobservador.com.uy",                     # Uruguay
    "emol.com", "latercera.com",                                # Chile
    "elcomercio.pe",                                            # Peru
    "jewishnews.com.ar", "semanario.com.ar",                    # Argentine Jewish press
    "hamodía.com.ar",
]
LATAM_TERMS = [
    "rabino Chabad arrestado", "rabino Lubavitch fraude",
    "rabino Chabad condenado", "Chabad abuso sexual rabino",
    "rabino Chabad acusado", "Lubavitch escándalo",
    "rabino judío fraude", "rabino judío abuso",
    "Chabad rabino preso", "rabino judío condenado",
]
LATAM_QUERIES = [f"{t} site:{s}" for s, t in itertools.product(LATAM_SITES[:8], LATAM_TERMS[:6])]

# Russian/Ukrainian
FSU_QUERIES = [
    "Хабад раввин арест мошенничество",
    "Хабад раввин осужден",
    "Хабад скандал раввин",
    "Любавич мошенничество",
    "раввин Хабад обвинение",
    "Хабад растрата Израиль",
    "Хабад Москва скандал",
    'site:rbc.ru Хабад раввин',
    'site:kommersant.ru Хабад',
    'site:novayagazeta.ru Хабад',
    'site:haaretz.co.il חב"ד רב נעצר',
    'site:ynet.co.il חב"ד רב הורשע',
    'site:maariv.co.il חב"ד רב מעצר',
    'site:walla.co.il חב"ד רב פלילי',
    # Ukrainian
    "Хабад рабин скандал Україна",
    "Хабад рабин шахрайство",
]

# French (Belgium/France — major Chabad presence)
FRENCH_SITES = ["lefigaro.fr", "lemonde.fr", "liberation.fr", "lepoint.fr", "jforum.fr", "linfo.re"]
FRENCH_TERMS = [
    "rabbin Chabad arrêté", "rabbin Lubavitch condamné",
    "rabbin Chabad fraude", "Chabad scandale rabbi",
    "rabbin pédophile Chabad", "rabbin juif condamné abus",
]
FRENCH_QUERIES = [f"site:{s} {t}" for s, t in itertools.product(FRENCH_SITES[:4], FRENCH_TERMS[:4])]

QUERIES = LATAM_QUERIES + FSU_QUERIES + FRENCH_QUERIES
print(f"prepared {len(QUERIES)} queries")

async def fire(q, key, out):
    h = hashlib.sha256(q.encode()).hexdigest()[:16]
    fp = out/f"{h}.json"
    if fp.exists(): return
    try:
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post("https://api.tavily.com/search", json={
                "api_key": key, "query": q, "max_results": 8, "search_depth": "basic",
            })
            r.raise_for_status()
            data = r.json()
            results = [{"title":x.get("title"),"url":x.get("url"),"snippet":x.get("content")} for x in data.get("results",[])]
            fp.write_text(json.dumps({"query":q,"engine":"tavily","results":results}, indent=2))
    except Exception as e:
        fp.write_text(json.dumps({"query":q,"engine":"tavily","results":[],"error":str(e)}))

async def main():
    out = ROOT/"data/raw/searches/bucket_x_latam"; out.mkdir(parents=True, exist_ok=True)
    sem = asyncio.Semaphore(5)
    async def one(q):
        async with sem: await fire(q, random.choice(KEYS), out)
    tasks=[one(q) for q in QUERIES]; done=0
    for c in asyncio.as_completed(tasks):
        await c; done+=1
        if done%15==0: print(f"  {done}/{len(QUERIES)}")
    print("X done")

asyncio.run(main())
