// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

interface IERC20 {
    function transfer(address to, uint256 amount) external returns (bool);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
}

/// @title ColonyForecastMarket
/// @notice Arc USDC escrow for ant forecast staking and deterministic settlement.
contract ColonyForecastMarket {
    enum MarketType {
        ThreeWay,
        Binary
    }

    enum Outcome {
        Home,
        Draw,
        Away
    }

    enum MarketStatus {
        None,
        Open,
        Settled,
        Canceled
    }

    struct Market {
        MarketType marketType;
        MarketStatus status;
        Outcome result;
        uint64 closeTime;
        uint16 treasuryFeeBps;
        uint256 totalStaked;
        uint256 totalClaimed;
        uint256 treasuryFee;
        string metadataURI;
    }

    IERC20 public immutable usdc;
    address public owner;
    address public treasury;

    mapping(bytes32 marketId => Market) public markets;
    mapping(bytes32 marketId => mapping(uint8 outcome => uint256 amount)) public outcomeStakes;
    mapping(bytes32 marketId => mapping(address ant => uint256 amount)) public antStake;
    mapping(bytes32 marketId => mapping(address ant => Outcome outcome)) public antOutcome;
    mapping(bytes32 marketId => mapping(address ant => bool claimed)) public claimed;

    event OwnershipTransferred(address indexed previousOwner, address indexed newOwner);
    event TreasuryChanged(address indexed previousTreasury, address indexed newTreasury);
    event MarketCreated(
        bytes32 indexed marketId,
        MarketType marketType,
        uint64 closeTime,
        uint16 treasuryFeeBps,
        string metadataURI
    );
    event VoteStaked(bytes32 indexed marketId, address indexed ant, Outcome indexed outcome, uint256 amount);
    event MarketSettled(
        bytes32 indexed marketId,
        Outcome indexed result,
        uint256 winningStake,
        uint256 losingPool,
        uint256 treasuryFee
    );
    event MarketCanceled(bytes32 indexed marketId);
    event Claimed(bytes32 indexed marketId, address indexed ant, uint256 payout);
    event TreasuryWithdrawn(address indexed treasury, uint256 amount);

    error NotOwner();
    error ZeroAddress();
    error InvalidMarket();
    error MarketAlreadyExists();
    error MarketNotOpen();
    error MarketNotSettled();
    error MarketNotCanceled();
    error MarketClosed();
    error InvalidOutcome();
    error ZeroAmount();
    error AlreadyVotedDifferentOutcome();
    error AlreadyClaimed();
    error NoStake();
    error NoWinners();
    error TransferFailed();
    error FeeTooHigh();

    modifier onlyOwner() {
        if (msg.sender != owner) revert NotOwner();
        _;
    }

    constructor(address usdc_, address treasury_) {
        if (usdc_ == address(0) || treasury_ == address(0)) revert ZeroAddress();
        usdc = IERC20(usdc_);
        owner = msg.sender;
        treasury = treasury_;
        emit OwnershipTransferred(address(0), msg.sender);
        emit TreasuryChanged(address(0), treasury_);
    }

    function transferOwnership(address newOwner) external onlyOwner {
        if (newOwner == address(0)) revert ZeroAddress();
        emit OwnershipTransferred(owner, newOwner);
        owner = newOwner;
    }

    function setTreasury(address newTreasury) external onlyOwner {
        if (newTreasury == address(0)) revert ZeroAddress();
        emit TreasuryChanged(treasury, newTreasury);
        treasury = newTreasury;
    }

    function createMarket(
        bytes32 marketId,
        MarketType marketType,
        uint64 closeTime,
        uint16 treasuryFeeBps,
        string calldata metadataURI
    ) external onlyOwner {
        if (marketId == bytes32(0)) revert InvalidMarket();
        if (markets[marketId].status != MarketStatus.None) revert MarketAlreadyExists();
        if (treasuryFeeBps > 2_000) revert FeeTooHigh();

        markets[marketId] = Market({
            marketType: marketType,
            status: MarketStatus.Open,
            result: Outcome.Home,
            closeTime: closeTime,
            treasuryFeeBps: treasuryFeeBps,
            totalStaked: 0,
            totalClaimed: 0,
            treasuryFee: 0,
            metadataURI: metadataURI
        });

        emit MarketCreated(marketId, marketType, closeTime, treasuryFeeBps, metadataURI);
    }

    function stake(bytes32 marketId, Outcome outcome, uint256 amount) external {
        Market storage market = markets[marketId];
        if (market.status != MarketStatus.Open) revert MarketNotOpen();
        if (market.closeTime != 0 && block.timestamp >= market.closeTime) revert MarketClosed();
        if (!_validOutcome(market.marketType, outcome)) revert InvalidOutcome();
        if (amount == 0) revert ZeroAmount();

        uint256 existingStake = antStake[marketId][msg.sender];
        if (existingStake != 0 && antOutcome[marketId][msg.sender] != outcome) {
            revert AlreadyVotedDifferentOutcome();
        }

        antStake[marketId][msg.sender] = existingStake + amount;
        antOutcome[marketId][msg.sender] = outcome;
        outcomeStakes[marketId][uint8(outcome)] += amount;
        market.totalStaked += amount;

        if (!usdc.transferFrom(msg.sender, address(this), amount)) revert TransferFailed();

        emit VoteStaked(marketId, msg.sender, outcome, amount);
    }

    function settle(bytes32 marketId, Outcome result) external onlyOwner {
        Market storage market = markets[marketId];
        if (market.status != MarketStatus.Open) revert MarketNotOpen();
        if (!_validOutcome(market.marketType, result)) revert InvalidOutcome();

        uint256 winningStake = outcomeStakes[marketId][uint8(result)];
        if (winningStake == 0) revert NoWinners();

        uint256 losingPool = market.totalStaked - winningStake;
        uint256 treasuryFee_ = (losingPool * market.treasuryFeeBps) / 10_000;

        market.status = MarketStatus.Settled;
        market.result = result;
        market.treasuryFee = treasuryFee_;

        emit MarketSettled(marketId, result, winningStake, losingPool, treasuryFee_);
    }

    function cancelMarket(bytes32 marketId) external onlyOwner {
        Market storage market = markets[marketId];
        if (market.status != MarketStatus.Open) revert MarketNotOpen();
        market.status = MarketStatus.Canceled;
        emit MarketCanceled(marketId);
    }

    function claim(bytes32 marketId) external returns (uint256 payout) {
        Market storage market = markets[marketId];
        if (market.status != MarketStatus.Settled) revert MarketNotSettled();
        if (claimed[marketId][msg.sender]) revert AlreadyClaimed();

        uint256 stakeAmount = antStake[marketId][msg.sender];
        if (stakeAmount == 0) revert NoStake();
        if (antOutcome[marketId][msg.sender] != market.result) revert NoStake();

        claimed[marketId][msg.sender] = true;
        payout = payoutOf(marketId, msg.sender);
        market.totalClaimed += payout;

        if (!usdc.transfer(msg.sender, payout)) revert TransferFailed();
        emit Claimed(marketId, msg.sender, payout);
    }

    function claimRefund(bytes32 marketId) external returns (uint256 refund) {
        Market storage market = markets[marketId];
        if (market.status != MarketStatus.Canceled) revert MarketNotCanceled();
        if (claimed[marketId][msg.sender]) revert AlreadyClaimed();

        refund = antStake[marketId][msg.sender];
        if (refund == 0) revert NoStake();

        claimed[marketId][msg.sender] = true;
        market.totalClaimed += refund;

        if (!usdc.transfer(msg.sender, refund)) revert TransferFailed();
        emit Claimed(marketId, msg.sender, refund);
    }

    function withdrawTreasury(bytes32 marketId) external {
        Market storage market = markets[marketId];
        if (market.status != MarketStatus.Settled) revert MarketNotSettled();
        uint256 amount = market.treasuryFee;
        if (amount == 0) revert ZeroAmount();
        market.treasuryFee = 0;
        if (!usdc.transfer(treasury, amount)) revert TransferFailed();
        emit TreasuryWithdrawn(treasury, amount);
    }

    function payoutOf(bytes32 marketId, address ant) public view returns (uint256) {
        Market storage market = markets[marketId];
        if (market.status != MarketStatus.Settled) return 0;
        uint256 stakeAmount = antStake[marketId][ant];
        if (stakeAmount == 0 || antOutcome[marketId][ant] != market.result) return 0;

        uint256 winningStake = outcomeStakes[marketId][uint8(market.result)];
        uint256 losingPool = market.totalStaked - winningStake;
        uint256 rewardPool = losingPool - market.treasuryFee;
        return stakeAmount + ((rewardPool * stakeAmount) / winningStake);
    }

    function marketTotals(bytes32 marketId)
        external
        view
        returns (uint256 home, uint256 draw, uint256 away, uint256 total)
    {
        home = outcomeStakes[marketId][uint8(Outcome.Home)];
        draw = outcomeStakes[marketId][uint8(Outcome.Draw)];
        away = outcomeStakes[marketId][uint8(Outcome.Away)];
        total = markets[marketId].totalStaked;
    }

    function _validOutcome(MarketType marketType, Outcome outcome) private pure returns (bool) {
        if (marketType == MarketType.ThreeWay) {
            return outcome == Outcome.Home || outcome == Outcome.Draw || outcome == Outcome.Away;
        }
        return outcome == Outcome.Home || outcome == Outcome.Away;
    }
}

