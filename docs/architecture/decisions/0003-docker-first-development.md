# ADR 0003: Docker-First Development

## Status

Accepted

## Context

Developers on Windows with Cursor should not install PostgreSQL/Redis/Python stacks locally.

## Decision

All runtime services run via Docker Desktop + Linux containers. Source is bind-mounted for hot reload.

## Consequences

One command (`docker compose up -d --build`) yields a portable foundation ready for VPS/cloud with the same compose-shaped topology.
