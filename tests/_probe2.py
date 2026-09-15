from bob.llm import _looks_like_spoken_answer

t = "I think it's clear and I'd shorten the background-notes rule."
q = "How do you feel about your current system prompt?"
print(_looks_like_spoken_answer(t, q))
