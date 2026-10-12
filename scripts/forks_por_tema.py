#!/usr/bin/env python3
"""Gera FORKS.md: os forks de um perfil do GitHub agrupados pelas tags `tema-*`.

Builds FORKS.md: a GitHub user's forks grouped by their `tema-*` topics.

Uso / usage:
    # A partir do GitHub (API REST pública; GITHUB_TOKEN opcional, mas recomendado)
    python scripts/forks_por_tema.py --user tatyquebralayout

    # Prévia a partir da proposta de temas (CSV), antes de as tags existirem
    python scripts/forks_por_tema.py --from-csv /caminho/forks-temas.csv

Só usa a biblioteca padrão do Python. Autora: Tatiana Barros.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path

API = "https://api.github.com"
PREFIXO_TEMA = "tema-"
RAIZ = Path(__file__).resolve().parent.parent
CONFIG_PADRAO = Path(__file__).resolve().parent / "forks_temas.json"
DESC_MAX = 140


@dataclass
class Fork:
    name: str
    url: str
    parent_full_name: str = ""
    parent_url: str = ""
    description: str = ""
    language: str = ""
    topics: list[str] = field(default_factory=list)
    em_duvida: bool = False  # só na prévia: classificação marcada como incerta

    @property
    def temas(self) -> list[str]:
        return sorted(t for t in self.topics if t.startswith(PREFIXO_TEMA))


# --------------------------------------------------------------------------
# Fonte 1: API REST do GitHub
# --------------------------------------------------------------------------

def _get(url: str, token: str | None):
    req = urllib.request.Request(url, headers={
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "forks-por-tema",
    })
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    for tentativa in range(3):
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            if e.code in (403, 429) and e.headers.get("X-RateLimit-Remaining") == "0":
                sys.exit(
                    "Limite da API do GitHub atingido. Rode com GITHUB_TOKEN definido "
                    "(sem token o limite é 60 chamadas/hora). / GitHub API rate limit hit; set GITHUB_TOKEN."
                )
            if e.code >= 500 and tentativa < 2:
                time.sleep(2 ** tentativa)
                continue
            sys.exit(f"Erro {e.code} em {url}: {e.read().decode(errors='replace')[:300]}")
        except urllib.error.URLError as e:
            if tentativa < 2:
                time.sleep(2 ** tentativa)
                continue
            sys.exit(f"Falha de rede em {url}: {e}")
    raise RuntimeError("inalcançável")


def forks_da_api(user: str, token: str | None) -> list[Fork]:
    if not token:
        print("Aviso: sem GITHUB_TOKEN; a API pública permite só 60 chamadas/hora.", file=sys.stderr)
    repos, page = [], 1
    while True:
        lote = _get(f"{API}/users/{user}/repos?type=owner&per_page=100&page={page}", token)
        repos.extend(lote)
        if len(lote) < 100:
            break
        page += 1

    forks = []
    for r in repos:
        if not r.get("fork"):
            continue
        # A listagem não traz o projeto original; o detalhe do repo traz.
        det = _get(f"{API}/repos/{r['full_name']}", token)
        parent = det.get("parent") or {}
        forks.append(Fork(
            name=r["name"],
            url=r["html_url"],
            parent_full_name=parent.get("full_name", ""),
            parent_url=parent.get("html_url", ""),
            description=r.get("description") or parent.get("description") or "",
            language=r.get("language") or parent.get("language") or "",
            topics=sorted(det.get("topics") or r.get("topics") or []),
        ))
    return forks


# --------------------------------------------------------------------------
# Fonte 2: CSV da proposta de temas (prévia)
# --------------------------------------------------------------------------

def forks_do_csv(caminho: Path, lista: Path | None) -> list[Fork]:
    extras = {}
    if lista is None:
        candidato = caminho.with_name("forks-lista.json")
        lista = candidato if candidato.exists() else None
    if lista is not None:
        for item in json.loads(lista.read_text(encoding="utf-8")):
            extras[item["name"]] = item

    forks = []
    with caminho.open(encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            ex = extras.get(row["name"], {})
            parent = row.get("parent_full_name") or ex.get("parent_full_name", "")
            forks.append(Fork(
                name=row["name"],
                url=row["html_url"],
                parent_full_name=parent,
                parent_url=ex.get("parent_url") or (f"https://github.com/{parent}" if parent else ""),
                description=ex.get("fork_description") or ex.get("parent_description") or row.get("motivo", ""),
                language=ex.get("parent_language") or "",
                topics=sorted(t.strip() for t in row.get("tags", "").split(";") if t.strip()),
                em_duvida=row.get("confianca", "").strip().lower() == "baixa",
            ))
    return forks


# --------------------------------------------------------------------------
# Markdown
# --------------------------------------------------------------------------

def texto_md(s: str) -> str:
    """Uma linha, curta e sem caracteres que quebrem o Markdown."""
    s = re.sub(r"\s+", " ", s or "").strip()
    if len(s) > DESC_MAX:
        corte = s[: DESC_MAX - 1].rsplit(" ", 1)[0].rstrip(" ,.;:-")
        s = corte + "…"
    s = s.replace("\\", "\\\\")
    s = s.replace("<", "&lt;").replace(">", "&gt;")
    return re.sub(r"([`*_\[\]|#])", r"\\\1", s)


def chave(fork: Fork):
    return (fork.name.casefold(), fork.name)


def titulo_padrao(tag: str) -> dict:
    nome = tag[len(PREFIXO_TEMA):].replace("-", " ").capitalize()
    return {"titulo_pt": nome, "titulo_en": nome, "intro_pt": "", "intro_en": "", "selo": f"badges/{tag}.svg"}


def bloco_secao(ancora: str, titulo: str, n: int, info: dict, nome_selo: str, linhas: list[str]) -> list[str]:
    out = [f'<a id="{ancora}"></a>', "", f"## {titulo} ({n})", ""]
    selo = info.get("selo")
    if selo and (RAIZ / selo).exists():
        out += [f'<img src="{selo}" height="24" alt="{nome_selo}">', ""]
    elif selo:
        out += [f"<!-- selo / badge: {selo} (Motion Designer) -->", ""]
    intro_pt, intro_en = info.get("intro_pt", "").strip(), info.get("intro_en", "").strip()
    if intro_pt or intro_en:
        out += [p for p in (intro_pt, intro_en) if p for p in (p, "")]
    else:
        out += ["<!-- intro: texto do Tech Writer em scripts/forks_temas.json / Tech Writer intro goes in scripts/forks_temas.json -->",
                "_Introdução em breve · Intro coming soon._", ""]
    return out + linhas + [""]


def linha_fork(fork: Fork, cfg: dict, tema_atual: str | None, topic_adotar: str, previa: bool) -> str:
    partes = [f"**[{fork.name}]({fork.url})**"]
    if fork.parent_full_name:
        partes.append(f"original: [{fork.parent_full_name}]({fork.parent_url})")
    if fork.description:
        partes.append(texto_md(fork.description))
    if fork.language:
        partes.append(f"`{fork.language}`")
    notas = []
    outros = [t for t in fork.temas if t != tema_atual]
    if tema_atual is not None and outros:
        notas.append("também em · also in " + ", ".join(
            f"[{cfg['temas'].get(t, titulo_padrao(t))['titulo_pt']}](#{t})" for t in outros))
    if tema_atual is not None and topic_adotar in fork.topics:
        notas.append("original arquivado · archived upstream")
    if previa and fork.em_duvida:
        notas.append("em dúvida · to review")
    linha = "- " + " · ".join(partes)
    if notas:
        linha += " _(" + "; ".join(notas) + ")_"
    return linha


def gerar(forks: list[Fork], cfg: dict, user: str, previa: bool) -> str:
    forks = sorted(forks, key=chave)
    adotar = cfg["adotar"]
    topic_adotar = adotar["topic"]

    grupos: dict[str, list[Fork]] = {}
    for f in forks:
        for t in f.temas:
            grupos.setdefault(t, []).append(f)
    ordem = sorted(grupos, key=lambda t: (-len(grupos[t]), t))  # mais forks primeiro; empate por nome
    para_adotar = [f for f in forks if topic_adotar in f.topics]
    sem_tema = [f for f in forks if not f.temas]

    def info(t):
        return cfg["temas"].get(t, titulo_padrao(t))

    md = ["<!-- Gerado por scripts/forks_por_tema.py. Não edite à mão: as mudanças somem na próxima execução. -->",
          "<!-- Generated by scripts/forks_por_tema.py. Do not edit by hand. -->", ""]
    md += ["# Forks por tema · Forks by theme", ""]
    if previa:
        md += ["> [!NOTE]",
               "> Prévia montada a partir da proposta de temas; as tags ainda não estão nos repositórios.",
               "> Preview built from the theme proposal; the tags are not on the repositories yet.", ""]
    md += [f"Os {len(forks)} forks de [{user}](https://github.com/{user}), separados pelos tópicos `{PREFIXO_TEMA}*` "
           "de cada repositório. Um fork com dois temas aparece nas duas seções.", "",
           f"The {len(forks)} forks of [{user}](https://github.com/{user}), grouped by each repository's "
           f"`{PREFIXO_TEMA}*` topics. A fork with two themes shows up in both sections.", ""]

    # Índice
    md += ["| Seção · Section | Forks |", "|---|---:|"]
    if para_adotar:
        md.append(f"| [{adotar['titulo_pt']} · {adotar['titulo_en']}](#{topic_adotar}) | {len(para_adotar)} |")
    for t in ordem:
        md.append(f"| [{info(t)['titulo_pt']} · {info(t)['titulo_en']}](#{t}) `{t}` | {len(grupos[t])} |")
    if sem_tema:
        st = cfg["sem_tema"]
        md.append(f"| [{st['titulo_pt']} · {st['titulo_en']}](#sem-tema) | {len(sem_tema)} |")
    md.append("")

    if para_adotar:
        linhas = []
        for f in para_adotar:
            temas = ", ".join(f"[{info(t)['titulo_pt']}](#{t})" for t in f.temas)
            linha = linha_fork(f, cfg, None, topic_adotar, previa)
            linhas.append(linha + (f" _(tema · theme: {temas})_" if temas else ""))
        md += bloco_secao(topic_adotar, f"{adotar['titulo_pt']} · {adotar['titulo_en']}", len(para_adotar),
                          adotar, f"{adotar['titulo_pt']} · {adotar['titulo_en']}", linhas)

    for t in ordem:
        i = info(t)
        nome = f"{i['titulo_pt']} · {i['titulo_en']}"
        md += bloco_secao(t, nome, len(grupos[t]), i, nome,
                          [linha_fork(f, cfg, t, topic_adotar, previa) for f in grupos[t]])

    if sem_tema:
        st = cfg["sem_tema"]
        md += bloco_secao("sem-tema", f"{st['titulo_pt']} · {st['titulo_en']}", len(sem_tema), st, "",
                          [linha_fork(f, cfg, None, topic_adotar, previa) for f in sem_tema])

    md += ["---", "",
           "<sub>Atualizado toda semana por uma GitHub Action · Updated weekly by a GitHub Action · "
           "Tatiana Barros</sub>", ""]
    return "\n".join(md)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--user", default=os.environ.get("GITHUB_REPOSITORY_OWNER", "tatyquebralayout"))
    ap.add_argument("--from-csv", type=Path, help="gera a prévia a partir do CSV de temas (colunas name, html_url, parent_full_name, tags, confianca)")
    ap.add_argument("--lista", type=Path, help="forks-lista.json com descrição e linguagem (padrão: ao lado do CSV)")
    ap.add_argument("--config", type=Path, default=CONFIG_PADRAO)
    ap.add_argument("--output", "-o", type=Path, default=RAIZ / "FORKS.md")
    args = ap.parse_args()

    cfg = json.loads(args.config.read_text(encoding="utf-8"))
    if args.from_csv:
        forks = forks_do_csv(args.from_csv, args.lista)
    else:
        forks = forks_da_api(args.user, os.environ.get("GITHUB_TOKEN"))

    texto = gerar(forks, cfg, args.user, previa=bool(args.from_csv))
    antigo = args.output.read_text(encoding="utf-8") if args.output.exists() else None
    if texto == antigo:
        print(f"{args.output.name}: sem mudanças ({len(forks)} forks).")
        return
    args.output.write_text(texto, encoding="utf-8")
    print(f"{args.output.name}: atualizado ({len(forks)} forks).")


if __name__ == "__main__":
    main()
