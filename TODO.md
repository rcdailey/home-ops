# Claude TODO List

- Create README.md for the repository
- Evaluate .mise.toml tools and determine what should be installed with brew per machine vs managed
  in mise -- tools that have to have their versions coordinated with config files in the repo should
  be one criteria.




I just compacted our chat history to free up context window space. So I need you to load the memory bank again, even if you think you
already loaded it. @/Users/robert/code/home-ops/.memory-bank/docker-to-k8s-migration.md

Capture everything we've discussed up to this point about Envoy before we do anything else.

I want you to come up with a plan/proposal for migrating from Cilium to Envoy. Requirements:

- SHould replace the internal and external gateway
- Resource name should be `envoy`
- Verify your work using the pre-commit logic. If there are valuable local and quick commands to verify changes like this, propose
those additions to pre-commit in your plan.
