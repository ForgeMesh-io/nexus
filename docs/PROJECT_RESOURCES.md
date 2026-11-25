# Optional project resources

A task can need a private input (for example, VIE's participant-owned game dump), a physical peripheral (for example, a personally owned PS Vita for a future project), or neither. ForgeMesh never needs the resource to join a swarm, and does not itself acquire or connect to it.

## Declare task requirements

In the verified swarm's protected `.forgemesh/resources.json`, map IDs to plain yes/no questions. IDs begin with a lowercase letter or digit and use at most 40 lowercase letters, digits, underscores or hyphens. Do not put download links, commands, paths, or secrets in questions.

```json
{
  "vita-device": "Do you have a personally owned PS Vita available for explicitly approved device tests?"
}
```

Put `"resource:vita-device"` in the task's `hardware` capability list. All listed requirements must be met to recommend that work, including for independent validators. Omitting the tag keeps a task open to participants without that resource. Resource availability is advisory and local; the GitHub coordinator does not verify possession or grant access.

For a swarm that declares private resources, maintain at least one independent task that needs neither special capabilities nor code execution (`"execution": "none"`). Keep a pipeline of useful work not gated on proprietary material: public-source research, algorithm changes against synthetic cases, documentation, and independent testing of public behavior. Split a resource-dependent validation run from the work others can do; link the related tasks and describe what each check can prove.

## Collaborate without sharing the resource

- A resource owner can propose an independently reproducible synthetic input, generator, or regression challenge via PR. Include provenance, a redistributable license, expected behavior, and what the reproduction does not cover. Prefer a small text fixture or generator over a binary attachment. Protect accepted test/fixture paths using the swarm's protected-path policy and repository review rules.
- Apply maintainer review before recommending shared fixtures. Review data and logs for private material or credentials. Do not download or execute files linked from arbitrary comments, and do not auto-unpack archives. Keep reviewed but untrusted test code in the existing no-network sandbox, with no private inputs or connected devices.
- The resource owner keeps dumps, firmware, keys, proprietary SDKs, and identifying information local and outside the checkout. Share only approved non-sensitive observations. An independent validator uses their own source or device when the original claim requires one; passing with a synthetic fixture does not verify real-device compatibility.
