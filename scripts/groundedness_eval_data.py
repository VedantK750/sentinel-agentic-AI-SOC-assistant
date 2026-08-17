"""Labeled (evidence, claim, expected_entailed) test set for benchmarking groundedness
judge candidates. Evidence is pulled verbatim from the real corpus (data/documents.json)
so this reflects the actual document shapes the judge sees in production -- long,
technical MITRE/Sigma prose, not short generic sentences.

Categories, all of which the judge needs to get right for a claim to be trustworthy:
  - supported: multiple independent phrasings of the SAME true fact, to directly probe
    the phrasing-consistency problem found in production (the "doas" 0.851-vs-0.125 case).
  - misattributed: a TRUE statement, but not actually said by *this* document (e.g. a
    subtechnique-specific fact attributed to the parent technique). Must be REJECTED.
  - hallucinated: fabricated, not supported anywhere in the evidence. Must be REJECTED.
  - overreach: a plausible-sounding inference that goes beyond what the text states.
    Must be REJECTED.
"""

CASES = [
    # ---- supported: T1059, three independent phrasings of the same opening fact ----
    {
        "id": "t1059-verbatim",
        "category": "supported",
        "evidence_doc": "mitre_attack:T1059",
        "claim": "Adversaries may abuse command and script interpreters to execute commands, scripts, or binaries.",
    },
    {
        "id": "t1059-paraphrase-long",
        "category": "supported",
        "evidence_doc": "mitre_attack:T1059",
        "claim": "Attackers can misuse command-line shells and scripting languages in order to run commands, scripts, or executable binaries on a system.",
    },
    {
        "id": "t1059-paraphrase-short",
        "category": "supported",
        "evidence_doc": "mitre_attack:T1059",
        "claim": "T1059 covers abusing script interpreters to run malicious commands.",
    },
    # ---- supported: T1195 supply chain, three phrasings ----
    {
        "id": "t1195-verbatim",
        "category": "supported",
        "evidence_doc": "mitre_attack:T1195",
        "claim": "Adversaries may manipulate products or product delivery mechanisms prior to receipt by a final consumer for the purpose of data or system compromise.",
    },
    {
        "id": "t1195-paraphrase-long",
        "category": "supported",
        "evidence_doc": "mitre_attack:T1195",
        "claim": "Before a product reaches its end customer, attackers can tamper with either the product itself or the way it is delivered, aiming to compromise data or systems.",
    },
    {
        "id": "t1195-paraphrase-short",
        "category": "supported",
        "evidence_doc": "mitre_attack:T1195",
        "claim": "Supply chain compromise means tampering with a product before the customer receives it.",
    },
    # ---- supported: mimikatz sigma rule, three phrasings ----
    {
        "id": "mimikatz-verbatim",
        "category": "supported",
        "evidence_doc": "sigma:189e3b02-82b2-4b90-9662-411eb64486d4",
        "claim": "Mimikatz is a credential dumper capable of obtaining plaintext Windows account logins and passwords.",
    },
    {
        "id": "mimikatz-paraphrase-long",
        "category": "supported",
        "evidence_doc": "sigma:189e3b02-82b2-4b90-9662-411eb64486d4",
        "claim": "This detection rule looks for use of Invoke-Mimikatz, a PowerShell-based credential dumping tool that can extract Windows account passwords in plaintext.",
    },
    {
        "id": "mimikatz-paraphrase-short",
        "category": "supported",
        "evidence_doc": "sigma:189e3b02-82b2-4b90-9662-411eb64486d4",
        "claim": "Mimikatz can steal Windows login passwords in plaintext.",
    },
    # ---- misattributed: true facts, wrong specific citation ----
    {
        "id": "misattrib-t1059-powershell",
        "category": "misattributed",
        "evidence_doc": "mitre_attack:T1059",
        "claim": "T1059 specifically refers to the use of PowerShell for credential dumping.",
    },
    {
        "id": "misattrib-t1195-pip-npm",
        "category": "misattributed",
        "evidence_doc": "mitre_attack:T1195",
        "claim": "Supply chain compromise commonly involves targeting pip and NPM packages as dependencies.",  # true, but that's T1195.001's specific content, not T1195's
    },
    {
        "id": "misattrib-t1003-mimikatz-detection",
        "category": "misattributed",
        "evidence_doc": "mitre_attack:T1003",
        "claim": "This technique can be detected using Sigma rules that look for Invoke-Mimikatz PowerShell scripts.",  # a real, true fact -- but not stated in T1003's own text
    },
    # ---- hallucinated: fabricated, unsupported anywhere ----
    {
        "id": "halluc-t1059-cve",
        "category": "hallucinated",
        "evidence_doc": "mitre_attack:T1059",
        "claim": "T1059 was assigned CVE-2019-0708 and patched by Microsoft in May 2019.",
    },
    {
        "id": "halluc-t1195-origin",
        "category": "hallucinated",
        "evidence_doc": "mitre_attack:T1195",
        "claim": "Supply chain compromise attacks were first documented by MITRE in 2015 following the Target Corporation breach.",
    },
    {
        "id": "halluc-mimikatz-author",
        "category": "hallucinated",
        "evidence_doc": "sigma:189e3b02-82b2-4b90-9662-411eb64486d4",
        "claim": "Mimikatz was developed by the NSA and later leaked in the Shadow Brokers dump.",
    },
    # ---- overreach: plausible inference beyond what the text actually states ----
    {
        "id": "overreach-t1059-detection-difficulty",
        "category": "overreach",
        "evidence_doc": "mitre_attack:T1059",
        "claim": "T1059 is extremely difficult to detect because command interpreters are used for both legitimate and malicious purposes.",  # plausible security-analyst inference, not actually stated in this text
    },
    {
        "id": "overreach-t1195-severity",
        "category": "overreach",
        "evidence_doc": "mitre_attack:T1195",
        "claim": "Supply chain compromise is considered one of the most severe attack vectors because it can affect thousands of downstream victims simultaneously.",
    },
    {
        "id": "overreach-t1003-prevalence",
        "category": "overreach",
        "evidence_doc": "mitre_attack:T1003",
        "claim": "OS Credential Dumping is the most commonly observed technique in real-world ransomware attacks.",
    },
]

# category -> whether a well-functioning judge should say "entailed" (True) or not (False)
EXPECTED_ENTAILED = {
    "supported": True,
    "misattributed": False,
    "hallucinated": False,
    "overreach": False,
}
