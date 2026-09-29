import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import type { Campaign, Client, SipTrunk, Team, User } from "./types";

export const useCampaigns = () =>
  useQuery({ queryKey: ["campaigns"], queryFn: () => api.get<Campaign[]>("/api/v1/campaigns") });

export const useClients = () =>
  useQuery({ queryKey: ["clients"], queryFn: () => api.get<Client[]>("/api/v1/clients") });

export const useTrunks = (enabled = true) =>
  useQuery({
    queryKey: ["sip-trunks"],
    queryFn: () => api.get<SipTrunk[]>("/api/v1/sip-trunks"),
    enabled,
  });

export const useTeams = () =>
  useQuery({ queryKey: ["teams"], queryFn: () => api.get<Team[]>("/api/v1/teams") });

export const useUsers = (enabled = true) =>
  useQuery({ queryKey: ["users"], queryFn: () => api.get<User[]>("/api/v1/users"), enabled });
