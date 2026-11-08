"""Auctioneer — collects bids, scores, and awards contracts.

Implements a contract-net-style auction:
    Broadcast contract → Collect bids → Score → Award
    Handle no-bid by relaxing constraints (max 2 rounds).
"""

from __future__ import annotations

import logging

from contractnet.core.agent import BaseAgent
from contractnet.core.types import Bid, Contract, ContractStatus

logger = logging.getLogger(__name__)


class Auctioneer:
    """Manages the bidding and award process for contracts.

    Responsibilities:
        - Broadcast open contracts to available agents
        - Collect and validate bids
        - Compute composite scores and select winner
        - Handle no-bid scenarios (relax constraints or mark impossible)

    Not responsible for:
        - Executing tasks
        - Quality validation
        - Conflict resolution
    """

    MAX_AUCTION_ROUNDS = 2

    def __init__(self) -> None:
        self._bid_history: dict[str, list[Bid]] = {}  # contract_id → bids
        # Scoring weights (tuned via experimentation)
        self.w_capability = 0.3
        self.w_cost = 0.2
        self.w_confidence = 0.3
        self.w_history = 0.2

    def auction(
        self,
        contract: Contract,
        agents: list[BaseAgent],
    ) -> Bid | None:
        """Run the full auction process for a contract.

        Args:
            contract: The contract to auction (must be OPEN status)
            agents: Available agents to bid

        Returns:
            Winning Bid, or None if no agent can fulfill the contract.
        """
        for round_num in range(1, self.MAX_AUCTION_ROUNDS + 1):
            logger.info(
                "Auction round %d for contract %s", round_num, contract.contract_id,
            )

            bids = self._collect_bids(contract, agents)
            self._bid_history[contract.contract_id] = bids

            if not bids:
                logger.warning(
                    "No bids in round %d for contract %s", round_num, contract.contract_id,
                )
                if round_num < self.MAX_AUCTION_ROUNDS:
                    self._relax_constraints(contract)
                    continue
                else:
                    logger.error(
                        "No bids after %d rounds for contract %s — marking impossible",
                        round_num, contract.contract_id,
                    )
                    contract.status = ContractStatus.IMPOSSIBLE
                    return None

            winner = self.evaluate_bids(bids, contract)
            logger.info(
                "Contract %s awarded to %s (score=%.3f)",
                contract.contract_id, winner.agent_id,
                self.compute_score(winner, contract),
            )
            return winner

        return None

    def evaluate_bids(self, bids: list[Bid], contract: Contract) -> Bid:
        """Select the best bid by composite score."""
        scored = [(bid, self.compute_score(bid, contract)) for bid in bids]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[0][0]

    def compute_score(self, bid: Bid, contract: Contract) -> float:
        """Compute composite score for a bid.

        score = w1*capability + w2*(1/cost_norm) + w3*confidence + w4*history

        Returns float in [0, 1].
        """
        capability = bid.capability_score
        cost_efficiency = 1.0 / (1.0 + bid.estimated_cost / 1000.0)
        confidence = bid.confidence
        # History factor would come from agent registry — using bid.confidence as proxy
        history = confidence  # simplified; can be enhanced with agent_registry

        return (
            self.w_capability * capability
            + self.w_cost * cost_efficiency
            + self.w_confidence * confidence
            + self.w_history * history
        )

    def rebroadcast(self, contract: Contract) -> None:
        """Re-open bidding for a contract after constraint relaxation."""
        contract.status = ContractStatus.OPEN

    def get_auction_history(self, contract_id: str) -> list[Bid]:
        """Get all bids for a contract across all rounds."""
        return self._bid_history.get(contract_id, [])

    # ──────────────────────────────────────────
    # Private methods
    # ──────────────────────────────────────────

    def _collect_bids(self, contract: Contract, agents: list[BaseAgent]) -> list[Bid]:
        """Ask each available agent to bid on the contract."""
        bids = []
        for agent in agents:
            if agent.is_busy:
                continue
            bid = agent.bid(contract)
            if bid is not None:
                bids.append(bid)
                logger.debug(
                    "Agent %s bid on contract %s (caps=%.2f, conf=%.2f, cost=%d)",
                    agent.agent_id, contract.contract_id,
                    bid.capability_score, bid.confidence, bid.estimated_cost,
                )
        return bids

    def _relax_constraints(self, contract: Contract) -> None:
        """Relax contract constraints to attract more bids."""
        c = contract.constraints
        c.max_tokens = int(c.max_tokens * 1.5)
        c.max_steps = int(c.max_steps * 1.5)
        c.quality_threshold = max(0.5, c.quality_threshold * 0.9)
        contract.deadline_steps = int(contract.deadline_steps * 1.5)
        logger.info(
            "Relaxed constraints for contract %s: tokens=%d, steps=%d, threshold=%.2f",
            contract.contract_id, c.max_tokens, c.max_steps, c.quality_threshold,
        )
