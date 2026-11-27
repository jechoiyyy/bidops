"""Network-free pieces of the live engine path (ADR-0081).

`responses` builds the exact OpenAI Responses API body and reads its usage and text, `framed`
builds the prompt parts and checks the JSON answer, and `ipc` is the transport the runner uses in
`--live-ipc` mode: it writes each request as a frame on stdout and reads the raw response from
stdin. The HTTP request and the API key live only in the BidOps supervisor.
"""
