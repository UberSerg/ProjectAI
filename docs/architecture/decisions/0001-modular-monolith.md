# ADR 0001: Modular Monolith

## Status

Accepted

## Context

ProjectAI needs clear boundaries for analytics, ML, LLM, and portfolio flows, but team size and stage do not justify microservice sprawl.

## Decision

Ship a modular monolith with explicit layers and module packages. Split into services later only when operational need appears.

## Consequences

Simpler local Docker Compose, shared types, single deployable backend image for API/worker/scheduler, with replaceable adapters behind ports.
