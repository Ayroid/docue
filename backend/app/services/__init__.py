"""Logic that outlives the endpoint that calls it.

A router here would be a mistake and a model here would be a mistake: this is
the layer where a rule lives once and both the API and a script can reach it.
`promotion.py` in particular is called from two endpoints -- an admin promoting
directly and an admin approving somebody else's request -- and the whole point
of it being here is that those two cannot drift on what "published" means.
"""
