"""Contract manager — creates, tracks, and transitions contract lifecycle."""

from __future__ import annotations

import logging

from contractnet.core.types import (
    Bid,
    Contract,
    ContractConstraints,
    ContractStatus,
    Task,
)

logger = logging.getLogger(__name__)


class ContractManager:
    """Manages contract lifecycle: create → open → bidding → award → closed.

    Responsibilities:
        - Create contracts from tasks with auto-inferred constraints
        - Track active contracts
        - Transition contract status through lifecycle
        - Not responsible for: executing tasks, arbitrating bids
    """

    # Default constraints per task type
    _DEFAULT_CONSTRAINTS: dict[str, ContractConstraints] = {
        "code": ContractConstraints(
            max_tokens=5000,
            max_steps=10,
            required_tools=["file_write", "code_run"],
            quality_threshold=0.8,
        ),
        "test": ContractConstraints(
            max_tokens=3000,
            max_steps=8,
            required_tools=["file_read", "code_run"],
            quality_threshold=0.85,
        ),
        "doc": ContractConstraints(
            max_tokens=2000,
            max_steps=5,
            required_tools=["file_read", "file_write"],
            quality_threshold=0.75,
        ),
        "analysis": ContractConstraints(
            max_tokens=4000,
            max_steps=10,
            required_tools=["data_read", "code_run"],
            quality_threshold=0.8,
        ),
        "design": ContractConstraints(
            max_tokens=3000,
            max_steps=6,
            required_tools=["file_write"],
            quality_threshold=0.8,
        ),
        "review": ContractConstraints(
            max_tokens=2000,
            max_steps=5,
            required_tools=["file_read"],
            quality_threshold=0.8,
        ),
    }

    def __init__(self) -> None:
        self._contracts: dict[str, Contract] = {}

    def create_contract(self, task: Task) -> Contract:
        """Create a contract from a task, auto-inferring constraints by task type."""
        constraints = self._DEFAULT_CONSTRAINTS.get(
            task.task_type, ContractConstraints()
        )
        contract = Contract(
            task_id=task.task_id,
            description=task.description,
            input_artifacts=task.input_artifacts,
            output_schema={"type": "string"},
            constraints=constraints,
            deadline_steps=constraints.max_steps + 5,
        )
        self._contracts[contract.contract_id] = contract
        logger.info(
            "Created contract %s for task %s (type=%s)",
            contract.contract_id, task.task_id, task.task_type,
        )
        return contract

    def open_bidding(self, contract: Contract) -> None:
        """Transition contract to bidding state."""
        contract.status = ContractStatus.BIDDING

    def close_bidding(self, contract: Contract) -> None:
        """Close bidding phase."""
        if contract.status == ContractStatus.BIDDING:
            contract.status = ContractStatus.OPEN

    def award(self, contract: Contract, bid: Bid) -> None:
        """Award contract to the winning bid."""
        contract.status = ContractStatus.AWARDED
        contract.awarded_bid_id = bid.bid_id
        contract.awarded_agent_id = bid.agent_id
        logger.info(
            "Contract %s awarded to agent %s", contract.contract_id, bid.agent_id,
        )

    def cancel(self, contract: Contract, reason: str = "") -> None:
        """Cancel a contract."""
        contract.status = ContractStatus.CANCELLED
        logger.warning("Contract %s cancelled: %s", contract.contract_id, reason)

    def mark_impossible(self, contract: Contract) -> None:
        """Mark contract as impossible to fulfill."""
        contract.status = ContractStatus.IMPOSSIBLE
        logger.warning("Contract %s marked impossible", contract.contract_id)

    def close(self, contract: Contract) -> None:
        """Close a successfully completed contract."""
        contract.status = ContractStatus.CLOSED

    def get_contract(self, contract_id: str) -> Contract | None:
        return self._contracts.get(contract_id)

    def get_active_contracts(self) -> list[Contract]:
        """Return all non-terminal contracts."""
        terminal = {ContractStatus.CLOSED, ContractStatus.CANCELLED, ContractStatus.IMPOSSIBLE}
        return [c for c in self._contracts.values() if c.status not in terminal]

    def get_contract_for_task(self, task_id: str) -> Contract | None:
        """Find the contract associated with a task."""
        for c in self._contracts.values():
            if c.task_id == task_id:
                return c
        return None
