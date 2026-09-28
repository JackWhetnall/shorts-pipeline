"""
The fact store: quiz facts from Wikidata, gathered ahead of any script.

- properties: which statements make quiz facts;
- wikidata: the query service and search;
- store: facts/facts.db;
- levels: how hard a fact is, from fame;
- categories: a quiz category mapped onto Wikidata;
- harvest: filling and growing the store;
- pick: facts for one round;
- keep: keeping every quiz category stocked, in the background.

See decision 049.
"""
