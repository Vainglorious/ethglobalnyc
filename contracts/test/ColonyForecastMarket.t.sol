// SPDX-License-Identifier: MIT
pragma solidity ^0.8.26;

import "../src/ColonyForecastMarket.sol";

contract MockUSDC {
    string public constant name = "Mock USDC";
    string public constant symbol = "USDC";
    uint8 public constant decimals = 6;

    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    function mint(address to, uint256 amount) external {
        balanceOf[to] += amount;
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        return true;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        require(balanceOf[msg.sender] >= amount, "balance");
        balanceOf[msg.sender] -= amount;
        balanceOf[to] += amount;
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        require(balanceOf[from] >= amount, "balance");
        require(allowance[from][msg.sender] >= amount, "allowance");
        allowance[from][msg.sender] -= amount;
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        return true;
    }
}

contract ColonyForecastMarketTest {
    MockUSDC usdc;
    ColonyForecastMarket market;

    address treasury = address(0xA11CE);
    address antA = address(0x1001);
    address antB = address(0x1002);
    address antC = address(0x1003);

    bytes32 marketId = keccak256("world-cup:group:brazil-morocco");

    function setUp() public {
        usdc = new MockUSDC();
        market = new ColonyForecastMarket(address(usdc), treasury);
        usdc.mint(antA, 10_000_000);
        usdc.mint(antB, 10_000_000);
        usdc.mint(antC, 10_000_000);
    }

    function testThreeWaySettlementPaysCorrectVoters() public {
        market.createMarket(marketId, ColonyForecastMarket.MarketType.ThreeWay, 0, 1_000, "ipfs://match");

        _stake(antA, ColonyForecastMarket.Outcome.Home, 1_000_000);
        _stake(antB, ColonyForecastMarket.Outcome.Draw, 2_000_000);
        _stake(antC, ColonyForecastMarket.Outcome.Home, 3_000_000);

        market.settle(marketId, ColonyForecastMarket.Outcome.Home);

        uint256 payoutA = market.payoutOf(marketId, antA);
        uint256 payoutC = market.payoutOf(marketId, antC);

        // Losing pool is 2 USDC. Treasury fee 10% = 0.2 USDC. Reward pool 1.8 USDC.
        // Winners staked 4 USDC total, so A receives 1 + 25% of 1.8, C receives 3 + 75% of 1.8.
        assertEq(payoutA, 1_450_000);
        assertEq(payoutC, 4_350_000);

        _claim(antA);
        _claim(antC);
        market.withdrawTreasury(marketId);

        assertEq(usdc.balanceOf(antA), 10_450_000);
        assertEq(usdc.balanceOf(antB), 8_000_000);
        assertEq(usdc.balanceOf(antC), 11_350_000);
        assertEq(usdc.balanceOf(treasury), 200_000);
    }

    function testBinaryRejectsDraw() public {
        bytes32 binaryId = keccak256("world-cup:ko:brazil-france");
        market.createMarket(binaryId, ColonyForecastMarket.MarketType.Binary, 0, 1_000, "");

        vmPrank(antA);
        usdc.approve(address(market), 1_000_000);

        vmPrank(antA);
        try market.stake(binaryId, ColonyForecastMarket.Outcome.Draw, 1_000_000) {
            fail();
        } catch {}
    }

    function testCannotChangeVoteOutcome() public {
        market.createMarket(marketId, ColonyForecastMarket.MarketType.ThreeWay, 0, 1_000, "");

        _stake(antA, ColonyForecastMarket.Outcome.Home, 500_000);

        vmPrank(antA);
        usdc.approve(address(market), 500_000);

        vmPrank(antA);
        try market.stake(marketId, ColonyForecastMarket.Outcome.Away, 500_000) {
            fail();
        } catch {}
    }

    function testCancelRefundsStakes() public {
        market.createMarket(marketId, ColonyForecastMarket.MarketType.ThreeWay, 0, 1_000, "");
        _stake(antA, ColonyForecastMarket.Outcome.Home, 1_000_000);

        market.cancelMarket(marketId);
        _refund(antA);

        assertEq(usdc.balanceOf(antA), 10_000_000);
    }

    function _stake(address ant, ColonyForecastMarket.Outcome outcome, uint256 amount) internal {
        vmPrank(ant);
        usdc.approve(address(market), amount);
        vmPrank(ant);
        market.stake(marketId, outcome, amount);
    }

    function _claim(address ant) internal {
        vmPrank(ant);
        market.claim(marketId);
    }

    function _refund(address ant) internal {
        vmPrank(ant);
        market.claimRefund(marketId);
    }

    function assertEq(uint256 a, uint256 b) internal pure {
        require(a == b, "assertEq failed");
    }

    function fail() internal pure {
        require(false, "expected revert");
    }

    function vmPrank(address caller) internal {
        Vm(address(uint160(uint256(keccak256("hevm cheat code"))))).prank(caller);
    }
}

interface Vm {
    function prank(address) external;
}

