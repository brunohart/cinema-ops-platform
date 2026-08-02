#!/usr/bin/env node
// seed-linear.mjs — deterministically seed the build backlog into Linear.
//
// The build-plan HTML is the single source of truth: this script reads the DAYS array
// and the EXPAND how-panels straight out of it, so the backlog can never drift from
// the plan it came from. Re-runnable: issues whose title already exists in the
// project are skipped, so a second run is a no-op rather than a duplication.
//
// The plan file is an input, not a repository artefact: pass --html explicitly.
// There is no default path, because a default that resolves only on the author's
// machine is the kind of green run that does not survive a clean clone.
//
// Usage:
//   node scripts/seed-linear.mjs --html ./plan.html --dry-run   # parse + render, no network
//   LINEAR_API_KEY=… node scripts/seed-linear.mjs --html ./plan.html
//   ... --limit 3                                        # only the first N (smoke test)
//   ... --json                                           # print the rendered backlog as JSON
//
// Mapping:
//   title       = task text, tags stripped
//   description = Model · Tool · Why · The move · Proof, as markdown
//   label       = day-0 … day-7
//   estimate    = 2 if the EXPAND entry has a real proof command, else 1
//   project     = cinema-ops-platform    · team = VDE    · one shared cycle

import fs from 'node:fs';

const argv = process.argv.slice(2);
const flag = (name) => argv.includes(`--${name}`);
const opt  = (name, def) => { const i = argv.indexOf(`--${name}`); return i >= 0 ? argv[i + 1] : def; };

const DRY   = flag('dry-run');
const JSONO = flag('json');
const LIMIT = opt('limit') ? parseInt(opt('limit'), 10) : Infinity;
const HTML  = opt('html');
const KEY   = process.env.LINEAR_API_KEY;

const TEAM_NAME    = 'VDE';
const PROJECT_NAME = 'cinema-ops-platform';
const CYCLE_NAME   = 'Build sprint — Day 0–7';

// ---------- extract the JS data blocks from the HTML (the data IS JavaScript) ----------
function extract(html, name, open, close, boundary) {
  const decl = `const ${name} =`;
  const d = html.indexOf(decl);
  if (d < 0) throw new Error(`could not find "${decl}" in ${HTML}`);
  const openIdx = html.indexOf(open, d + decl.length);
  const bIdx = html.indexOf(boundary, openIdx);
  const region = html.slice(openIdx, bIdx < 0 ? html.length : bIdx);
  const body = region.slice(0, region.lastIndexOf(close) + 1);
  // eslint-disable-next-line no-new-func
  return new Function(`"use strict"; return (${body});`)();
}

// ---------- html → text/markdown helpers ----------
const decode = (s) => s
  .replace(/&amp;/g, '&').replace(/&lt;/g, '<').replace(/&gt;/g, '>')
  .replace(/&quot;/g, '"').replace(/&#39;/g, "'").replace(/&apos;/g, "'").replace(/&nbsp;/g, ' ');
const stripTags = (s) => s.replace(/<[^>]+>/g, '');
// prose: keep line breaks, drop formatting tags
const prose = (s) => decode(stripTags((s || '').replace(/<br\s*\/?>/gi, '\n'))).replace(/[ \t]+\n/g, '\n').trim();
// single line (titles, tool, model titles)
const line = (s) => prose(s).replace(/\s+/g, ' ').trim();
// code blocks: unwrap comment <span>s, drop remaining tags, THEN decode entities
const code = (s) => decode((s || '').replace(/<\/?span[^>]*>/g, '').replace(/<[^>]+>/g, '')).replace(/\s+$/, '');

// a "proof command" exists only if some non-comment, non-blank line survives
function hasRealProof(proofRaw) {
  if (!proofRaw) return false;
  return code(proofRaw).split('\n').map((l) => l.trim()).some((l) => l && !l.startsWith('#'));
}

function description(e, modelTitles) {
  if (!e) return '';
  const parts = [];
  const head = [];
  if (e.model) head.push(`**Model ${e.model} — ${line(modelTitles[e.model] || '')}**`);
  if (e.tool)  head.push(`**Tool:** ${line(e.tool)}`);
  if (head.length) parts.push(head.join(' · '));
  if (e.why)   parts.push(`**Why** — ${prose(e.why)}`);
  if (e.move)  parts.push('**The move**\n```\n' + code(e.move) + '\n```');
  if (e.proof) parts.push('**Proof**\n```\n' + code(e.proof) + '\n```');
  return parts.join('\n\n');
}

// ---------- build the backlog ----------
function buildBacklog() {
  if (!HTML) {
    throw new Error('--html <path-to-plan.html> is required (no default; see the header comment)');
  }
  if (!fs.existsSync(HTML)) {
    throw new Error(`plan file not found: ${HTML}`);
  }
  const html = fs.readFileSync(HTML, 'utf8');
  const EXPAND = extract(html, 'EXPAND', '{', '}', 'MODEL_TITLES');
  const MODEL_TITLES = extract(html, 'MODEL_TITLES', '{', '}', 'HOW PANEL');
  const DAYS = extract(html, 'DAYS', '[', ']', 'const TERMS');

  const issues = [];
  DAYS.forEach((d, dayNum) => {
    d.tasks.forEach((task, j) => {
      const key = `${d.id}.${j}`;
      const e = EXPAND[key];
      issues.push({
        key,
        label: `day-${dayNum}`,
        title: line(task),
        estimate: hasRealProof(e && e.proof) ? 2 : 1,
        description: description(e, MODEL_TITLES),
      });
    });
  });
  return issues;
}

// ---------- Linear GraphQL ----------
async function gql(query, variables) {
  const res = await fetch('https://api.linear.app/graphql', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', Authorization: KEY },
    body: JSON.stringify({ query, variables }),
  });
  const json = await res.json();
  if (json.errors) throw new Error(JSON.stringify(json.errors));
  return json.data;
}

async function resolveTeam() {
  const { teams } = await gql(`{ teams(first: 250) { nodes { id name key } } }`);
  const t = teams.nodes.find((x) => x.key === TEAM_NAME || x.name.toLowerCase() === TEAM_NAME.toLowerCase());
  if (!t) throw new Error(`team "${TEAM_NAME}" not found (have: ${teams.nodes.map((x) => x.key).join(', ')})`);
  return t;
}

async function resolveProject() {
  const { projects } = await gql(`{ projects(first: 250) { nodes { id name } } }`);
  const p = projects.nodes.find((x) => x.name.toLowerCase() === PROJECT_NAME.toLowerCase());
  if (!p) throw new Error(`project "${PROJECT_NAME}" not found (have: ${projects.nodes.map((x) => x.name).join(', ')})`);
  return p;
}

async function ensureLabels(teamId, names) {
  const { team } = await gql(
    `query($id:String!){ team(id:$id){ labels(first:250){ nodes { id name } } } }`, { id: teamId });
  const map = {};
  for (const n of team.labels.nodes) map[n.name] = n.id;
  for (const name of names) {
    if (map[name]) continue;
    const d = await gql(
      `mutation($input:IssueLabelCreateInput!){ issueLabelCreate(input:$input){ success issueLabel{ id name } } }`,
      { input: { name, teamId } });
    map[name] = d.issueLabelCreate.issueLabel.id;
    console.log(`  label created: ${name}`);
  }
  return map;
}

async function ensureCycle(teamId) {
  try {
    const starts = new Date();
    const ends = new Date(Date.now() + 14 * 86400000);
    const d = await gql(
      `mutation($input:CycleCreateInput!){ cycleCreate(input:$input){ success cycle{ id name } } }`,
      { input: { teamId, name: CYCLE_NAME, startsAt: starts.toISOString(), endsAt: ends.toISOString() } });
    console.log(`  cycle created: ${CYCLE_NAME}`);
    return d.cycleCreate.cycle.id;
  } catch (err) {
    console.warn(`  ! cycle not created (cycles may be disabled on the team) — issues will be created without one.\n    ${err.message}`);
    return null;
  }
}

async function existingTitles(projectId) {
  const set = new Set();
  let after = null;
  do {
    const d = await gql(
      `query($id:String!,$after:String){ project(id:$id){ issues(first:250, after:$after){ nodes{ title } pageInfo{ hasNextPage endCursor } } } }`,
      { id: projectId, after });
    for (const n of d.project.issues.nodes) set.add(n.title);
    after = d.project.issues.pageInfo.hasNextPage ? d.project.issues.pageInfo.endCursor : null;
  } while (after);
  return set;
}

async function main() {
  const backlog = buildBacklog();
  const wanted = backlog.slice(0, LIMIT);

  if (JSONO) { console.log(JSON.stringify(wanted, null, 2)); return; }

  // summary
  const byDay = {};
  for (const i of backlog) byDay[i.label] = (byDay[i.label] || 0) + 1;
  const est2 = backlog.filter((i) => i.estimate === 2).length;
  console.log(`Parsed ${backlog.length} tasks from ${HTML}`);
  console.log(`  per day: ${Object.entries(byDay).map(([k, v]) => `${k}:${v}`).join('  ')}`);
  console.log(`  estimate 2 (has proof command): ${est2}   ·   estimate 1: ${backlog.length - est2}\n`);

  if (DRY) {
    console.log('--- first 3 rendered issues (dry run, no network) ---\n');
    for (const it of backlog.slice(0, 3)) {
      console.log(`### [${it.label} · est ${it.estimate}] ${it.title}\n`);
      console.log(it.description + '\n\n----------------------------------------\n');
    }
    console.log(`(dry run) would create ${wanted.length} issue(s). Re-run with LINEAR_API_KEY set to create them.`);
    return;
  }

  if (!KEY) { console.error('LINEAR_API_KEY is not set. Export it, or use --dry-run.'); process.exit(1); }

  const team = await resolveTeam();
  const project = await resolveProject();
  console.log(`team ${team.key} (${team.id})  ·  project ${project.name} (${project.id})`);

  const labels = await ensureLabels(team.id, [...new Set(wanted.map((i) => i.label))]);
  const cycleId = await ensureCycle(team.id);
  const seen = await existingTitles(project.id);

  let created = 0, skipped = 0, failed = 0, sendEstimate = true;
  for (const it of wanted) {
    if (seen.has(it.title)) { skipped++; console.log(`  skip (exists): ${it.title}`); continue; }
    const base = {
      teamId: team.id, projectId: project.id, title: it.title,
      description: it.description, labelIds: [labels[it.label]],
      ...(cycleId ? { cycleId } : {}),
    };
    const attempt = async (withEstimate) => gql(
      `mutation($input:IssueCreateInput!){ issueCreate(input:$input){ success issue{ identifier url } } }`,
      { input: withEstimate ? { ...base, estimate: it.estimate } : base });
    try {
      let d;
      try { d = await attempt(sendEstimate); }
      catch (err) {
        if (sendEstimate && /estimat/i.test(err.message)) {
          console.warn('  ! estimates disabled on this team — continuing without estimates.');
          sendEstimate = false; d = await attempt(false);
        } else throw err;
      }
      const iss = d.issueCreate.issue;
      created++; console.log(`  ${iss.identifier}  [${it.label} · est ${it.estimate}]  ${it.title}`);
    } catch (err) {
      failed++; console.error(`  FAILED: ${it.title}\n    ${err.message}`);
    }
  }
  console.log(`\nDone. created ${created} · skipped ${skipped} · failed ${failed}`);
  console.log('Proof: open the project in Linear, pick any issue, copy its branch name.');
}

main().catch((e) => { console.error(e); process.exit(1); });
