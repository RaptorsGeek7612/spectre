// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.35;

import {Script, console} from "forge-std/Script.sol";
import {Voting} from "../src/Voting.sol";

contract VotingScript is Script {
    function run() external returns (Voting voting) {
        vm.startBroadcast();
        voting = new Voting();
        vm.stopBroadcast();

        console.log("Voting deployed at:", address(voting));
    }
}
