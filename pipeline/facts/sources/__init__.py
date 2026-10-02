"""
Where imported quiz questions come from (decision 061): the Open Trivia
Database (`opentdb`) and pub-quiz websites (`web`). Each only gathers raw
questions into the intake table, at no model cost beyond reading web pages;
`pipeline.facts.intake` turns them into bank questions.
"""
