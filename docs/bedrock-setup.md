# Running the LLM features on AWS Bedrock

Everything needed to move the three LLM features (document extraction, exit
notes, Ask Vantage chat) from Groq to AWS Bedrock in **eu-west-2 (London)**.

There are two halves and they fail for different reasons, so it's worth
keeping them separate in your head:

| Half | Where you do it | What goes wrong |
|---|---|---|
| **AWS side** | AWS console, once per account | model not granted, IAM policy too narrow |
| **App side** | `.env` on each machine | wrong model id, missing region |

Work through Part A, then Part B, then run the verifier in Part C. Do not
skip the verifier — see "Why verification matters" at the bottom.

---

## Part A — the AWS side (once per account)

### A1. Pick the region and stay in it

Everything below must happen in **eu-west-2 / London**. Bedrock is a
regional service: models granted in `us-east-1` do not exist in `eu-west-2`,
and the console silently shows you a different region's state if you drift.
Check the region selector in the top-right of the console on every screen.

### A2. Grant model access

This is separate from IAM and is the single most common blocker — valid
credentials with an ungranted model still fail.

1. Console → **Amazon Bedrock** → region **eu-west-2**
2. Left sidebar, bottom → **Model access**
3. **Modify model access** (or *Enable specific models* on a fresh account)
4. Tick the Anthropic Claude model you intend to use
5. **Next** → **Submit**

Anthropic models may ask for a one-time use-case questionnaire (company
name, what you're building, whether output is shown to end users). It's a
form, not a review queue — access is normally granted in under a minute.

Status must read **Access granted**. "Available to request" means you are
not done.

### A3. Create the IAM policy

Console → **IAM** → **Policies** → **Create policy** → **JSON** tab.
Paste this, replacing `<ACCOUNT_ID>` with your 12-digit account number
(top-right of the console, under your username):

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Sid": "InvokeClaude",
      "Effect": "Allow",
      "Action": [
        "bedrock:InvokeModel",
        "bedrock:InvokeModelWithResponseStream"
      ],
      "Resource": [
        "arn:aws:bedrock:*::foundation-model/anthropic.claude-*",
        "arn:aws:bedrock:eu-west-2:<ACCOUNT_ID>:inference-profile/eu.anthropic.claude-*"
      ]
    },
    {
      "Sid": "DiscoverModels",
      "Effect": "Allow",
      "Action": [
        "bedrock:ListFoundationModels",
        "bedrock:ListInferenceProfiles",
        "bedrock:GetInferenceProfile"
      ],
      "Resource": "*"
    }
  ]
}
```

Name it something like `companysim-bedrock-invoke` and create it.

**Why there are two resource ARNs, and why one has a `*` region.** In EU
regions Claude is served through a *cross-region inference profile*. You
call the profile, and AWS may route the actual inference to `eu-west-1`,
`eu-west-3` or `eu-central-1` depending on capacity. Your policy therefore
has to allow both the profile itself (regional, account-scoped) **and** the
underlying foundation model in whichever region served it — hence
`arn:aws:bedrock:*::foundation-model/...`.

A policy that names only `eu-west-2` for the foundation model looks correct,
passes review, and then throws `AccessDeniedException` intermittently —
only when routing happens to land outside London. That is a genuinely
horrible bug to diagnose after the fact, which is why the `*` is there
deliberately rather than by laziness.

(The empty field in `arn:aws:bedrock:*::foundation-model/` is not a typo.
Foundation-model ARNs carry no account id, so the account segment is empty.)

### A4. Create the user and attach the policy

Console → **IAM** → **Users** → **Create user**

1. Name: `companysim-bedrock`
2. **Do not** tick "Provide user access to the AWS Management Console" —
   this identity is for API calls only, and a console password on a
   service identity is extra attack surface for no benefit
3. **Next** → **Attach policies directly** → search for
   `companysim-bedrock-invoke` → tick it
4. **Next** → **Create user**

### A5. Create the access key

Open the user you just made → **Security credentials** tab → **Create
access key**.

1. Use case: **Application running outside AWS**
2. Tick the confirmation, **Next**
3. Description tag (optional): `companysim dev laptop`
4. **Create access key**

You now see **Access key ID** and **Secret access key**.

> **The secret is shown exactly once.** Click *Download .csv* or copy both
> values somewhere safe right now. If you lose it you cannot recover it —
> you delete the key and make a new one, which is not a disaster, just
> annoying.

Do not paste these into a chat window, a ticket, or a commit.

---

## Part B — the app side (on each machine)

### B1. Pull and install

```bash
git pull origin feat/llm-document-ingestion
python -m venv .venv
.venv\Scripts\activate            # Windows
pip install -e ".[dev,ml,viz,api,llm]"
cd webapp && npm install && cd ..
```

`.[llm]` installs both provider SDKs. If this machine is committed to
Bedrock and you would rather not carry the Groq SDK, use
`.[dev,ml,viz,api,bedrock]` instead — nothing imports either SDK at module
scope, so the Groq path just becomes unavailable rather than broken.

### B2. Create `.env`

```bash
cp .env.example .env
```

**`.env` is gitignored and does not come across with the pull.** That is
deliberate — credentials should never travel through git — but it means
each machine needs its own, created by hand. `.env.example` is the template
that *does* travel, and it documents every variable.

Open `.env` and set:

```ini
# Bedrock is the default, so this line is optional — set it anyway to make
# the intent explicit to whoever reads the file next.
COMPANYSIM_LLM_PROVIDER=bedrock

AWS_DEFAULT_REGION=eu-west-2
AWS_ACCESS_KEY_ID=AKIA...................
AWS_SECRET_ACCESS_KEY=........................................

COMPANYSIM_BEDROCK_MODEL_ID=<from B3>

COMPANYSIM_LLM_INGEST=1
COMPANYSIM_LLM_EXIT_NOTES=0
COMPANYSIM_LLM_CHAT=0
```

`GROQ_API_KEY` can be left blank — nothing reads it under the Bedrock
default. If one is set and Bedrock has no credentials, the status endpoint
says so explicitly rather than only reporting missing AWS keys.

**The region is not optional.** Bedrock's endpoint is regional and boto3
raises `NoRegionError` rather than picking a default, so an otherwise
perfect config with no region fails at the first call.

### B3. Find the real model id

Do not trust the default in `.env.example`. Ask your own account what it can
call:

```bash
aws bedrock list-inference-profiles --region eu-west-2 \
  --query "inferenceProfileSummaries[].inferenceProfileId" --output table
```

No AWS CLI installed? The app can answer it too:

```bash
.venv/Scripts/python -c "import boto3; print(*[p['inferenceProfileId'] for p in boto3.client('bedrock', region_name='eu-west-2').list_inference_profiles()['inferenceProfileSummaries']], sep='\n')"
```

Copy whichever `eu.anthropic.claude-...` id you granted in A2 into
`COMPANYSIM_BEDROCK_MODEL_ID`.

> **The `eu.` prefix is mandatory in eu-west-2.** A bare
> `anthropic.claude-3-5-sonnet-20240620-v1:0` is rejected with
> `ValidationException`; it must be
> `eu.anthropic.claude-3-5-sonnet-20240620-v1:0`. This is the failure you
> are most likely to hit first, and the error message does not say "add a
> prefix" — it just says the model id is invalid.

---

## Part C — verify before you trust it

```bash
set -a; . ./.env; set +a                              # Git Bash
.venv/Scripts/python scripts/check_llm_provider.py
```

PowerShell has no `set -a`. Load the file the same way
`scripts/start-dev.ps1` does:

```powershell
Get-Content .env | Where-Object { $_ -match '^\s*[^#\s][^=]*=' } |
  ForEach-Object { $n,$v = $_ -split '=',2; Set-Item -Path "Env:$($n.Trim())" -Value $v.Trim() }
.venv\Scripts\python scripts\check_llm_provider.py
```

It skips comments and blank lines, and splits on the **first** `=` only, so
a secret containing `=` survives intact.

Either way the values live only in that shell session — open a new terminal
and you need to load them again.

A healthy run:

```
provider: bedrock  (COMPANYSIM_LLM_PROVIDER)

[  OK  ] boto3 installed
[  OK  ] region eu-west-2
[  OK  ] credentials resolved via env
[  OK  ] STS identity arn:aws:iam::123456789012:user/companysim-bedrock
[  OK  ] model id eu.anthropic.claude-sonnet-4-20250514-v1:0

--- live call ---
[  OK  ] reply '{"ok": true}'
[  OK  ] tokens in=65 out=8 total=73

--- feature flags ---
[  OK  ] document extraction: on  (COMPANYSIM_LLM_INGEST)
[ WARN ] LLM exit notes: off  (COMPANYSIM_LLM_EXIT_NOTES)
[ WARN ] Ask Vantage chat: off  (COMPANYSIM_LLM_CHAT)

ready
```

Exit code 0 means a real call actually succeeded. Anything else exits 1.

### Why verification matters here specifically

Every LLM feature in this codebase **fails silently on purpose**:

- extraction returns nothing and parks the document as `needs_review`
- exit notes fall back to the template generator
- chat shows "temporarily unavailable"

Those are the right behaviours in production — a model outage must never
take down a page — but they mean a misconfiguration looks *identical* to a
model that simply declined. You would upload ten documents, see ten
"needs review", and have no way to tell whether your IAM policy is wrong or
the documents are bad.

The verifier removes that ambiguity by checking each layer separately and
making one real call, so a failure names the layer that broke.

### Reading a failure

| What you see | What it actually means | Fix |
|---|---|---|
| `no AWS region set` | boto3 found no region | `AWS_DEFAULT_REGION=eu-west-2` |
| `boto3 resolved no credentials` | keys not exported into this shell | you edited `.env` but didn't `set -a; . ./.env` |
| `InvalidClientTokenId` from STS | the keys are wrong/deleted | recreate the access key (A5) |
| `SignatureDoesNotMatch` | secret key mistyped | recopy — a trailing space breaks it |
| `AccessDeniedException` after a good STS line | credentials fine, permissions not | the IAM policy (A3) — check the `*` region on the foundation-model ARN |
| `ValidationException` / "invalid model" | wrong id, or access not granted | re-run B3; confirm A2 says *Access granted* |
| `ThrottlingException` | config is correct, you're rate-limited | retry; request a quota increase if persistent |
| `Could not connect to the endpoint` | network/proxy/VPN | not an AWS config problem |

### Then start it

```powershell
.\scripts\start-dev.ps1        # Windows
```

```bash
./scripts/start-dev.sh         # macOS / Linux / Git Bash
```

These load `.env` themselves, start both servers, wait for readiness and
smoke-test them — so you do not need to repeat the loading step above
before running the app. Stop with `.\scripts\stop-dev.ps1`, or Ctrl-C on
the shell script.

(There is also a `/run-servers` Claude Code skill in `.claude/skills/`. It
documents the same two commands and is only a convenience for that editor —
the scripts above are the dependency-free path and work anywhere.)

The token meter in the top-right will now show your Bedrock model name —
usage rows record whichever model actually served each call, so nothing
needs updating when you switch.

---

## Part D — the production upgrade: stop using static keys

Everything above uses an access key + secret, which is right for a laptop
and wrong for a server. The problem with static keys is not that they're
insecure in principle — it's that they are **long-lived secrets that live
on disk**, so they leak through backups, logs, screenshots and images, and
rotating them is a manual job somebody has to remember.

An **IAM role** solves this: AWS injects short-lived credentials that
rotate automatically, and there is no secret on the filesystem at all.

**Nothing in the code changes.** `llm/provider.py` never reads
`AWS_ACCESS_KEY_ID` by name — it hands authentication to boto3's standard
credential chain, which finds a role automatically. That's also why
readiness is decided by asking boto3 what it *resolved* rather than
checking for environment variables a role never sets.

To switch, when this eventually runs on AWS:

1. **IAM → Roles → Create role**
2. Trusted entity: **AWS service** → EC2 (or ECS task / Lambda, whichever
   is hosting it)
3. Attach the same `companysim-bedrock-invoke` policy from A3
4. Attach the role to the instance: EC2 → *Actions* → *Security* →
   *Modify IAM role*
5. In `.env` on that host, **delete** `AWS_ACCESS_KEY_ID` and
   `AWS_SECRET_ACCESS_KEY`. Keep `AWS_DEFAULT_REGION`.
6. Re-run the verifier — it should now report
   `credentials resolved via iam-role` instead of `via env`

Then delete the static access key in IAM so it can't be used again.

For a middle ground on a shared laptop, `aws configure` writes a named
profile to `~/.aws/credentials` and you set `AWS_PROFILE=companysim`
instead of the two key variables — the secret is out of the project
directory, though still long-lived on disk.

---

## Part E — decommissioning Groq

Once Bedrock is verified and you no longer want the Groq path live:

1. **Rotate/revoke the key** at
   [console.groq.com/keys](https://console.groq.com/keys). Any key that has
   ever been pasted into a chat, a terminal, or a screenshot should be
   considered public — revoking is free and takes one click.
2. Blank `GROQ_API_KEY` in `.env` on every machine.

You do **not** need to uninstall the `groq` package or remove the code path.
Both SDKs ship together on purpose: the provider is chosen at runtime, so a
deployment that could only install one of them would fail on a config change
rather than on a deploy — which is the worse place to find out. Keeping Groq
installed also means `COMPANYSIM_LLM_PROVIDER=groq` remains a one-line
rollback if Bedrock has a bad day.

---

## What is actually different between the two providers

Mostly nothing, by design — `llm/provider.py` normalizes both onto one
interface. Two differences are worth knowing:

**JSON mode.** Groq constrains decoding to valid JSON at the sampler, so
its replies are always bare. Bedrock's Converse API has no equivalent, and
a model told "return only JSON" still routinely writes "Here is the
extracted data:" first or adds a closing pleasantry. `parse_json_object`
therefore strips markdown fences *and* falls back to the first balanced
`{...}` in the reply, counting braces with string-awareness so a brace
inside `summary_text` doesn't confuse it.

This is deliberately **not** solved by forcing a tool call with the target
schema, which would guarantee structure but destroy the refusal contract: a
forced call has to populate every required field, so a model that should
have reported a missing rating would invent one instead. Tolerating chatter
is the cheaper mistake than manufacturing data.

Either way the same pydantic schema validates the result, and that is the
check which actually protects the database — the difference changes how
often a call is *wasted*, never whether a bad value can reach an employee
record.

**Tool calling.** Groq uses OpenAI-shaped `tool_calls` with JSON-string
arguments; Bedrock uses `toolUse` blocks with already-parsed dicts. The
provider layer normalizes both to a `ToolCall` with a real dict, so the chat
loop is unchanged. `tests/test_llm_provider.py` asserts this structurally —
a broken translation wouldn't raise anywhere, it would just look like a
model that kept refusing.
