// SPDX-License-Identifier: UNLICENSED
pragma solidity ^0.8.35;

import {Test} from "forge-std/Test.sol";
import {Voting} from "../src/Voting.sol";

contract VotingTest is Test {
    Voting voting;

    address owner = address(this);
    address alice = makeAddr("alice");
    address bob = makeAddr("bob");
    address stranger = makeAddr("stranger");

    event VoterRegistered(address voterAddress);
    event WorkflowStatusChange(
        Voting.WorkflowStatus previousStatus, Voting.WorkflowStatus newStatus
    );
    event ProposalRegistered(uint256 proposalId);
    event Voted(address voter, uint256 proposalId);

    function setUp() public {
        voting = new Voting();
        voting.addVoter(owner);
        voting.addVoter(alice);
        voting.addVoter(bob);
    }

    // ::::::::::::: DEPLOYMENT ::::::::::::: //

    function test_StartsInRegisteringVotersPhase() public view {
        assertEq(uint256(voting.workflowStatus()), uint256(Voting.WorkflowStatus.RegisteringVoters));
    }

    function test_OwnerIsTheDeployer() public view {
        assertEq(voting.owner(), owner);
    }

    // ::::::::::::: REGISTRATION ::::::::::::: //

    function test_OwnerCanRegisterVoters() public view {
        Voting.Voter memory voter = voting.getVoter(alice);
        assertTrue(voter.isRegistered);
    }

    function test_AddVoterEmitsVoterRegistered() public {
        vm.expectEmit(true, false, false, true, address(voting));
        emit VoterRegistered(stranger);
        voting.addVoter(stranger);
    }

    function test_OnlyOwnerCanAddVoter() public {
        vm.prank(alice);
        vm.expectRevert();
        voting.addVoter(stranger);
    }

    function test_CannotRegisterTheSameVoterTwice() public {
        vm.expectRevert("Already registered");
        voting.addVoter(alice);
    }

    function test_CannotRegisterVotersOnceRegistrationIsClosed() public {
        voting.startProposalsRegistering();

        vm.expectRevert("Voters registration is not open yet");
        voting.addVoter(stranger);
    }

    function test_NonVoterCannotReadVoterOrProposalData() public {
        vm.startPrank(stranger);

        vm.expectRevert("You're not a voter");
        voting.getVoter(owner);

        vm.expectRevert("You're not a voter");
        voting.getOneProposal(0);

        vm.stopPrank();
    }

    // ::::::::::::: PROPOSALS ::::::::::::: //

    function test_CannotAddProposalBeforeRegistrationStarts() public {
        vm.prank(alice);
        vm.expectRevert("Proposals are not allowed yet");
        voting.addProposal("Reduce taxes");
    }

    function test_CannotAddEmptyProposal() public {
        voting.startProposalsRegistering();

        vm.prank(alice);
        vm.expectRevert("You can't submit an empty proposal");
        voting.addProposal("");
    }

    function test_StartProposalsRegisteringSeedsGenesisProposal() public {
        voting.startProposalsRegistering();

        Voting.Proposal memory genesis = voting.getOneProposal(0);
        assertEq(genesis.description, "GENESIS");
    }

    function testFuzz_AddProposalIncrementsProposalCount(uint8 proposalCount) public {
        vm.assume(proposalCount > 0 && proposalCount <= 20);
        voting.startProposalsRegistering();

        for (uint8 i = 0; i < proposalCount; i++) {
            vm.prank(alice);
            voting.addProposal(string.concat("Proposal #", vm.toString(i)));
        }

        // id 0 is GENESIS, so the last proposal's id is proposalCount
        Voting.Proposal memory last = voting.getOneProposal(proposalCount);
        assertEq(last.description, string.concat("Proposal #", vm.toString(proposalCount - 1)));
    }

    // ::::::::::::: VOTING ::::::::::::: //

    function test_FullWorkflow_WinnerIsMostVotedProposal() public {
        voting.startProposalsRegistering();

        vm.prank(alice);
        voting.addProposal("Proposal A"); // id 1 (id 0 is the GENESIS proposal)
        vm.prank(bob);
        voting.addProposal("Proposal B"); // id 2

        voting.endProposalsRegistering();
        voting.startVotingSession();

        vm.prank(alice);
        voting.setVote(2);
        vm.prank(bob);
        voting.setVote(2);
        voting.setVote(1); // owner votes for proposal 1

        voting.endVotingSession();

        vm.expectEmit(true, true, false, true, address(voting));
        emit WorkflowStatusChange(
            Voting.WorkflowStatus.VotingSessionEnded, Voting.WorkflowStatus.VotesTallied
        );
        voting.tallyVotes();

        assertEq(uint256(voting.workflowStatus()), uint256(Voting.WorkflowStatus.VotesTallied));
        assertEq(voting.winningProposalID(), 2);
    }

    function test_CannotVoteTwice() public {
        voting.startProposalsRegistering();
        voting.endProposalsRegistering();
        voting.startVotingSession();

        vm.startPrank(alice);
        voting.setVote(0);
        vm.expectRevert("You have already voted");
        voting.setVote(0);
        vm.stopPrank();
    }

    function test_CannotVoteForANonExistentProposal() public {
        voting.startProposalsRegistering();
        voting.endProposalsRegistering();
        voting.startVotingSession();

        vm.expectRevert("Proposal not found");
        voting.setVote(99);
    }

    function test_CannotVoteBeforeSessionStarts() public {
        voting.startProposalsRegistering();
        voting.endProposalsRegistering();

        vm.expectRevert("Voting session hasn't started yet");
        voting.setVote(0);
    }

    // ::::::::::::: WORKFLOW GUARDS ::::::::::::: //

    function test_CannotTallyBeforeVotingSessionEnds() public {
        voting.startProposalsRegistering();
        voting.endProposalsRegistering();
        voting.startVotingSession();

        vm.expectRevert("Current status is not voting session ended");
        voting.tallyVotes();
    }

    function test_OnlyOwnerCanAdvanceTheWorkflow() public {
        vm.startPrank(alice);

        vm.expectRevert();
        voting.startProposalsRegistering();

        vm.stopPrank();
    }
}
