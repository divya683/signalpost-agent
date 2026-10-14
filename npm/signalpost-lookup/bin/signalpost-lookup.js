#!/usr/bin/env node
// Live, single-company Norwegian registry lookup. Zero dependencies: every
// call below is a plain fetch() against a public official JSON API, no
// Python, no build step, no account signup. Mirrors the same endpoints and
// field mapping as the reference Python agent's official.py, reimplemented
// standalone so `npx signalpost-lookup <org>` works with nothing installed
// but Node.

const BRREG_ENTITY = (org) => `https://data.brreg.no/enhetsregisteret/api/enheter/${org}`;
const BRREG_ROLES = (org) => `${BRREG_ENTITY(org)}/roller`;
const BRREG_ACCOUNTS = (org) => `https://data.brreg.no/regnskapsregisteret/regnskap/${org}`;
const BRREG_SUBUNITS = (org) => `https://data.brreg.no/enhetsregisteret/api/underenheter?overordnetEnhet=${org}&size=1000`;
const UA = "SignalpostResearchPOC/1.0 (npm CLI; bounded qualification run)";
const NARRATE_MODEL = "claude-haiku-4-5-20251001";

function parseArgs(argv) {
  const args = { org: null, question: "Who leads this company and what financial facts and locations are available?", llmKey: process.env.ANTHROPIC_API_KEY || null };
  const rest = [];
  for (let i = 0; i < argv.length; i += 1) {
    const token = argv[i];
    if (token === "--question") { args.question = argv[++i]; continue; }
    if (token === "--llm-key") { args.llmKey = argv[++i]; continue; }
    rest.push(token);
  }
  args.org = (rest[0] || "").replace(/\D/g, "");
  return args;
}

async function getJson(url) {
  const start = Date.now();
  const response = await fetch(url, { headers: { "User-Agent": UA, Accept: "application/json" } });
  const elapsed = (Date.now() - start) / 1000;
  if (response.status === 404) return { status: 404, body: null, elapsed };
  if (!response.ok) throw new Error(`${url} returned HTTP ${response.status}`);
  return { status: response.status, body: await response.json(), elapsed };
}

function roleRecords(body) {
  const roles = [];
  for (const group of body?.rollegrupper || []) {
    for (const item of group.roller || []) {
      const person = item.person || {};
      const name = person.navn || {};
      const entity = item.enhet || {};
      const displayName = [name.fornavn, name.mellomnavn, name.etternavn].filter(Boolean).join(" ") || entity.navn;
      if (!displayName) continue;
      roles.push({
        claim: item.type?.beskrivelse || group.type?.beskrivelse || "Role",
        value: displayName,
        source_url: BRREG_ROLES(body._org),
      });
    }
  }
  return roles;
}

function financialFacts(records, org) {
  const facts = [];
  for (const item of (records || []).slice(0, 1)) {
    const push = (claim, value) => { if (value !== undefined && value !== null) facts.push({ claim, value, source_url: BRREG_ACCOUNTS(org) }); };
    const period = item.regnskapsperiode;
    push("Reporting period", period ? `${period.fraDato} to ${period.tilDato}` : undefined);
    push("Revenue", item.resultatregnskapResultat?.driftsresultat?.driftsinntekter?.sumDriftsinntekter);
    push("Operating result", item.resultatregnskapResultat?.driftsresultat?.driftsresultat);
    push("Annual result", item.resultatregnskapResultat?.aarsresultat);
    push("Assets", item.eiendeler?.sumEiendeler);
    push("Debt", item.egenkapitalGjeld?.gjeldOversikt?.sumGjeld);
  }
  return facts;
}

function locationFacts(body, org) {
  const rows = body?._embedded?.underenheter || [];
  return rows.slice(0, 10).map((row) => ({
    claim: "Registered subunit",
    value: `${row.navn} (${row.beliggenhetsadresse?.kommune || row.postadresse?.kommune || "?"})`,
    source_url: BRREG_SUBUNITS(org),
  }));
}

async function narrate(apiKey, facts, question) {
  const factLines = facts.map((f) => `- ${f.claim}: ${f.value}`).join("\n");
  const prompt = `Write one short, plain paragraph summarizing the following verified facts about a Norwegian company, in response to the question. Use only the facts given, do not add anything not listed, and do not invent numbers.\n\nQuestion: ${question}\n\nFacts:\n${factLines}`;
  const response = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: { "Content-Type": "application/json", "x-api-key": apiKey, "anthropic-version": "2023-06-01" },
    body: JSON.stringify({ model: NARRATE_MODEL, max_tokens: 300, messages: [{ role: "user", content: prompt }] }),
  });
  if (!response.ok) throw new Error(`Anthropic API returned HTTP ${response.status}`);
  const parsed = await response.json();
  return (parsed.content || []).map((block) => block.text || "").join("");
}

async function main() {
  const args = parseArgs(process.argv.slice(2));
  if (!args.org) {
    console.error("Usage: signalpost-lookup <organisation-number> [--question \"...\"] [--llm-key sk-ant-...]");
    process.exitCode = 1;
    return;
  }

  console.log(`-> Fetching identity from the live Brønnøysund registry for ${args.org} ...`);
  const entity = await getJson(BRREG_ENTITY(args.org));
  if (entity.status === 404) {
    console.log(`   ${args.org} was not found in the registry. Nothing further to fetch.`);
    return;
  }
  const name = entity.body.navn;
  const municipality = entity.body.forretningsadresse?.kommune;
  console.log(`   done in ${entity.elapsed.toFixed(2)}s. Identity confirmed: ${name} (${municipality})`);

  console.log("-> Fetching financials, roles and registered subunits ...");
  const t0 = Date.now();
  const [accounts, roles, subunits] = await Promise.all([
    getJson(BRREG_ACCOUNTS(args.org)).catch(() => ({ status: 0, body: null, elapsed: 0 })),
    getJson(BRREG_ROLES(args.org)).catch(() => ({ status: 0, body: null, elapsed: 0 })),
    getJson(BRREG_SUBUNITS(args.org)).catch(() => ({ status: 0, body: null, elapsed: 0 })),
  ]);
  console.log(`   done in ${((Date.now() - t0) / 1000).toFixed(2)}s (3 requests)`);

  const facts = [
    ...financialFacts(accounts.body, args.org),
    ...(roles.body ? roleRecords({ ...roles.body, _org: args.org }) : []),
    ...locationFacts(subunits.body, args.org),
  ];
  const retrievedAt = new Date().toISOString();

  console.log(`\nTotal cited facts: ${facts.length}\n`);
  console.log("=".repeat(60));
  console.log(`ANSWER: ${args.question}`);
  console.log("=".repeat(60));
  for (const fact of facts) {
    console.log(`- ${fact.claim}: ${fact.value}`);
    console.log(`    source: ${fact.source_url}`);
    console.log(`    retrieved: ${retrievedAt}`);
  }

  if (args.llmKey) {
    console.log("\n" + "=".repeat(60));
    console.log("AI-GENERATED SUMMARY (not a cited fact, bring-your-own-key, off by default)");
    console.log("=".repeat(60));
    try {
      console.log(await narrate(args.llmKey, facts, args.question));
    } catch (error) {
      console.log(`Could not generate summary: ${error.message}`);
    }
  }
}

main().catch((error) => {
  console.error(`Error: ${error.message}`);
  process.exitCode = 1;
});
