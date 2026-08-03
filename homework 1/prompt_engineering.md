# Prompt Engineering Concepts

This document explains three prompt engineering concepts I applied while building the multi-expert system for Homework 1. It also evaluates how effective each technique was based on practical tests performed against the live application.

---

## 1. Role and Persona Prompting

### What It Is

Role or persona prompting assigns the model a specific identity, responsibility, and domain of expertise instead of asking it to respond as a general-purpose assistant.

Each expert in the system begins with a clear role definition:

> "You are a {{ role }}, an expert in {{ domain }}."

For example, the Database Read Expert is defined as an expert in generating SQL queries for a résumé database, while the Orchestrator is defined as an expert in decomposing user requests into an ordered plan of expert calls.

### What I Observed

Giving each expert a narrow and explicit identity made the model's output significantly more consistent with what the downstream code expected.

For example, when I asked:

> "How long did they work at Al-Azhar University of Gaza?"

the Database Read Expert reliably returned only a SQL `SELECT` statement, without explanations, markdown formatting, or conversational filler. This was essential because `execute_read_query()` directly checks whether the generated output begins with `SELECT` before executing it.

Without a clearly defined role, a general-purpose model may respond with text such as:

> "Sure, here is a query you can use:"

Although this response is understandable to a human, it would break the application's parsing and execution logic.

### Effectiveness

**Effectiveness: High**

Role prompting was highly effective because it reduced irrelevant text and encouraged each expert to remain within its assigned responsibility. However, the role description worked best when combined with an explicit output instruction such as:

> "Return SQL only. Do not include explanations or markdown."

The role established the expert's identity, while the output rule ensured that the response remained machine-parseable.

---

## 2. Structured Output Constraints

### What It Is

Structured output constraints require the model to follow a precise response format. These constraints control not only what the model should produce, but also how the result must be represented so that the application can process it safely.

For example, the Database Write Expert was instructed to generate a single executable Python statement and to assign a predefined result message to a variable named `outcome`.

Expected messages included formats such as:

- `New <element> added to the <table> table.`
- `Element already exists in the <table> table.`

### What I Observed

The format constraint worked well, but one test revealed an important limitation.

I asked the system:

> "Add PHP as a skill to E-Commerce Mobile App."

However, I did not provide a skill level. The model generated code similar to the following:

```python
db.insertRows(
    'skills',
    ['experience_id', 'name', 'skill_level'],
    [
        "(SELECT experience_id FROM experiences WHERE name = 'E-Commerce Mobile App')",
        'PHP',
        None
    ]
)
```

The execution failed with the following database error:

```text
NOT NULL constraint failed: skills.skill_level
```

The database schema requires `skill_level` to contain a value, but the user's request did not provide one. The model preserved the expected output structure, yet it did not have enough information to generate valid content.

When I repeated the request and explicitly included a level:

> "Add PHP as a skill to E-Commerce Mobile App with skill level 7."

the same expert generated valid code, and the insertion succeeded.

### Effectiveness

**Effectiveness: Very High, with an important limitation**

Structured output prompting reliably controlled the shape of the model's response. The expert consistently produced executable code and assigned the required `outcome` variable.

However, output formatting cannot replace input validation. A model may follow the required structure perfectly while still producing invalid values when essential information is missing.

This test showed that the system should validate required fields before calling the Write Expert. For example, if `skill_level` is required, the application should either:

1. ask the user to provide it,
2. apply a clearly documented default value, or
3. reject the operation before attempting the database insert.

The main lesson is that structured prompting controls response format, but application-level validation is still necessary to guarantee correctness.

---

## 3. Task Decomposition with Few-Shot Examples

### What It Is

Task decomposition involves breaking a compound user request into smaller, ordered steps that can be assigned to specialized experts.

The Orchestrator was given a few-shot example showing how a conditional request should be transformed into an ordered list of expert calls.

Example:

> Request: "Does he know React? If not, add it to his most recent experience."

Expected plan:

```text
[
  "handle_ai_chat_request(role='Database Read Expert', ...)",
  "handle_ai_chat_request(role='Database Write Expert', ...)"
]
```

The example teaches the Orchestrator that it must first check whether the skill exists and then perform the write operation only when necessary.

### What I Observed

I tested the system with the following request:

> "Does he know Laravel? If not, add it to E-Commerce Mobile App with skill level 6."

The Orchestrator correctly generated and executed a two-step plan.

A simplified version of the console output was:

```text
[Orchestrator] Executing Database Read Expert:
"Does he have Laravel listed as a skill?"

[Database Read Expert] Generated:
SELECT 1 FROM skills WHERE name = 'Laravel' LIMIT 1;

[Orchestrator] Executing Database Write Expert:
"Add Laravel to E-Commerce Mobile App with skill level 6."

[Database Write Expert] Generated:
... outcome = "New Laravel added to the skills table."
```

The read operation ran first and returned no matching record. Only after that did the write operation insert the new skill. This matched the conditional logic of the original request.

### Reliability Limitation

Task decomposition was highly effective for explicit compound requests, but it was not perfectly reliable for simpler routing decisions.

For example, the question:

> "How long did they work at Al-Azhar University?"

was usually routed to the Database Read Expert. However, in one test using a smaller free-tier model, the Orchestrator incorrectly routed it to the Content Expert.

This indicates that routing still depends on the model's judgment about which expert best matches the request. Few-shot examples improve this judgment, but they do not eliminate routing errors completely.

### Effectiveness

**Effectiveness: High**

Few-shot examples helped the Orchestrator understand both the required sequence and the dependency between steps. The method was especially useful when a request contained conditions such as:

- "If not, add it."
- "Check first, then update."
- "Find the latest record and modify it."

However, additional safeguards could improve reliability, such as:

- validating expert names before execution,
- using rule-based routing for obvious database operations,
- adding more routing examples,
- requiring the Orchestrator to provide a short reason for each selected expert, and
- preventing write operations unless the required read result has been confirmed.

---

## 4. Exact-Name Matching Limitation

Another important observation was the system's dependence on literal database values.

When I asked about:

> "Al-Azhar University"

the system returned no result. However, when I used the complete stored name:

> "Al-Azhar University of Gaza"

the query worked correctly.

This behavior shows that the agents were relying on exact or near-exact string matching rather than semantic entity resolution. The system did not automatically infer that both names referred to the same institution.

This limitation could be reduced by:

- using case-insensitive matching,
- applying SQL `LIKE` queries,
- normalizing organization names,
- storing aliases,
- using fuzzy matching, or
- asking the user to confirm the intended entity when multiple matches are possible.

For example, instead of relying only on:

```sql
WHERE organization_name = 'Al-Azhar University'
```

the system could use a normalized or partial-match query such as:

```sql
WHERE LOWER(organization_name) LIKE '%al-azhar university%'
```

This would make the system more tolerant of shortened names while still requiring appropriate safeguards when several records match.

---

## General Takeaway

The experiments showed that prompt engineering was most effective when it constrained both the expert's role and the exact format of its output.

Role prompting helped each expert remain focused on its assigned responsibility. Structured output constraints made responses easier for the application to parse and execute. Few-shot task decomposition helped the Orchestrator translate compound requests into correctly ordered expert calls.

However, prompting alone could not solve every problem.

The main limitations appeared when the system had to:

- infer missing required information,
- choose between experts with overlapping responsibilities,
- recognize shortened or alternative entity names, or
- guarantee that generated values satisfied database constraints.

Therefore, the strongest design combines prompt engineering with traditional software safeguards. These include input validation, schema-aware checks, rule-based routing, result verification, transaction control, and clearer error handling.

Overall, the tests demonstrated that prompt engineering can make a multi-expert system substantially more consistent and machine-compatible, but it should be treated as one layer of the solution rather than a replacement for application logic and validation.
