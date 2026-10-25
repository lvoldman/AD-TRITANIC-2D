# Project conventions

- Write GUI text, documentation, comments and docstrings in English.
- Add explicit return annotations (`-> ...`) to Python functions and methods.
  Use `-> None` for functions without a return value and specific collection
  element types where applicable.
- Annotate Python parameters, instance attributes, constants and local variable
  declarations with `: Type` wherever the syntax supports it. Use concrete
  collection types, TypedDict records and Protocol interfaces instead of bare
  dict/list or Any when the structure is known. `self`/`cls`, enum members and
  comprehension/exception bindings may rely on their contextual types.
- Explain purpose, units, side effects and non-obvious decisions in readable
  comments or docstrings. Avoid comments that merely repeat the next statement.
- Add a short English purpose comment before every function or method, above
  its decorators when present. A docstring inside the body does not replace it.
- Never execute commands that physically move motors unless the user explicitly
  requests that hardware operation. Validate changes using offline tests.
