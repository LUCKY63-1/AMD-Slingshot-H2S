from agno.agent import Agent
from agno.os import AgentOS
from agno.db.sqlite import SqliteDb
from agno.workflow import Step, Workflow
from agno.workflow.parallel import Parallel
from agno.tools.websearch import WebSearchTools
from agno.tools.yfinance import YFinanceTools
from agno.tools.tavily import TavilyTools
from agno.tools import tool

from agno.models.nvidia import Nvidia
from agno.db.in_memory import InMemoryDb 
from pydantic import BaseModel, Field
from typing import List
from dotenv import load_dotenv
import os
import json
from urllib.parse import urlencode
from urllib.request import urlopen
from urllib.error import URLError, HTTPError

load_dotenv()
db = SqliteDb(db_file="tmp/travel.db", session_table="workflow_session")


@tool
def convert_currency(from_currency: str, to_currency: str, amount: float) -> str:
    """Convert currency using UnirateAPI.

    Args:
        from_currency: Source currency code (e.g., "USD")
        to_currency: Target currency code (e.g., "EUR")
        amount: Amount to convert

    Returns:
        Converted amount result or an error message.
    """
    api_key = os.getenv("RATE_CONVERTER_API_KEY")
    if not api_key:
        return (
            "Currency conversion failed: RATE_CONVERTER_API_KEY is not set."
        )

    url = "https://api.unirateapi.com/api/convert"
    params = urlencode(
        {
            "api_key": api_key,
            "from": from_currency.upper(),
            "to": to_currency.upper(),
            "amount": amount,
        }
    )

    try:
        with urlopen(f"{url}?{params}", timeout=20) as response:
            payload = json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        return f"Currency conversion failed: HTTP {exc.code} from UnirateAPI."
    except URLError as exc:
        return f"Currency conversion failed: {exc.reason}."
    except Exception as exc:
        return f"Currency conversion failed: {exc}."

    if "result" in payload and "to" in payload:
        return f"Converted amount: {payload['result']} {payload['to']}"

    return f"Currency conversion failed: {payload}"

# ---------------------------------------------------------------------------
# Structured Input Schema (applied at Workflow level, NOT agent level)
# ---------------------------------------------------------------------------
class TravelRequest(BaseModel):
    destination: str = Field(description="Travel destination city/country")
    travel_purpose: str = Field(description="Purpose: leisure, business, honeymoon, etc.")
    travel_companions: str = Field(description="Solo, couple, family, group")
    travel_dates: str = Field(description="Preferred travel dates")
    departure_location: str = Field(description="City/airport of departure")
    date_flexibility: str = Field(description="Flexible, fixed, or slightly flexible")
    accommodation_type: str = Field(description="Hotel, hostel, Airbnb, resort, etc.")
    budget: str = Field(description="Total budget with currency, e.g. '$3000 USD'")
    interests_activities: List[str] = Field(description="E.g. hiking, museums, food tours")
    travel_style: str = Field(description="Luxury, budget, backpacker, mid-range")
    duration: str = Field(description="Trip duration, e.g. '7 days'")
    budget_flexibility: str = Field(description="Strict, moderate, or flexible")

# ---------------------------------------------------------------------------
# Independent Research Agents (NO input_schema here)
# ---------------------------------------------------------------------------
weather_agent = Agent(
    name="Weather Specialist",
    model=Nvidia(id="meta/llama-3.3-70b-instruct"),
    tools=[WebSearchTools(backend="google"), TavilyTools()],
    instructions=[
        "You are a weather and climate research specialist for travel planning.",
        "Return destination-specific findings only; avoid generic travel advice.",
        "Using the user's `destination`, `travel_dates`, and `date_flexibility`:",
        "- Research historical weather patterns and forecasts for the destination during the travel dates.",
        "- Highlight temperature ranges, precipitation likelihood, and any extreme weather risks.",
        "- Suggest the best time windows if dates are flexible.",
        "- Recommend packing essentials based on expected conditions.",
        "- Output exactly: Best travel window, day-level weather notes, risk alerts, and a packing checklist.",
    ],
    db=InMemoryDb(),
    markdown=True,
)

destination_agent = Agent(
    name="Destination Researcher",
    model=Nvidia(id="meta/llama-3.3-70b-instruct"),
    tools=[WebSearchTools(backend="google"), TavilyTools()],
    instructions=[
        "You are a destination research specialist.",
        "Return concrete, destination-specific details only; avoid generic summaries.",
        "Using the user's `destination`, `travel_purpose`, and `travel_companions`:",
        "- Provide an overview of the destination: culture, language, currency, and safety tips.",
        "- Highlight visa/entry requirements based on `departure_location`.",
        "- Note any travel advisories or health precautions.",
        "- Tailor cultural tips to the `travel_purpose` (e.g. business etiquette vs. leisure customs).",
        "- Output as: Entry requirements, safety/health alerts, local norms, and practical traveler notes.",
    ],
    db=InMemoryDb(),
    markdown=True,
)

accommodation_agent = Agent(
    name="Accommodation Advisor",
    model=Nvidia(id="meta/llama-3.3-70b-instruct"),
    tools=[WebSearchTools(backend="google")],
    instructions=[
        "You are an accommodation research specialist.",
        "Give real options with approximate prices; do not provide generic hotel advice.",
        "Using `destination`, `accommodation_type`, `budget`, `travel_style`, `duration`, and `travel_companions`:",
        "- Research and recommend accommodation options matching the preferred `accommodation_type`.",
        "- Provide price ranges per night and total estimated cost for the `duration`.",
        "- Suggest neighborhoods/areas best suited for the `travel_purpose`.",
        "- Flag options within `budget` and note if `budget_flexibility` allows upgrades.",
        "- Output at least 3 named stay options.",
        "- Output as a table with: property name, area, nightly price, trip total, pros, and budget fit.",
    ],
    db=InMemoryDb(),
    markdown=True,  
)

transport_agent = Agent(
    name="Transportation Specialist",
    model=Nvidia(id="meta/llama-3.3-70b-instruct"),
    tools=[WebSearchTools(backend="google")],
    instructions=[
        "You are a transportation research specialist.",
        "Provide concrete route and cost options; avoid generic transport advice.",
        "Using `departure_location`, `destination`, `travel_dates`, `budget`, and `travel_style`:",
        "- Research flight options, layovers, and estimated costs from `departure_location`.",
        "- Suggest local transport options at the destination (public transit, car rental, rideshare).",
        "- Recommend the best transport mode based on `travel_companions` (e.g. car rental for families).",
        "- Provide cost estimates for both intercity and local transport within `budget`.",
        "- Output at least 2 named transport choices (e.g., specific flight/rail/bus options).",
        "- Output as: outbound/inbound options, local mobility plan, estimated total transport cost.",
    ],
    db=InMemoryDb(),
    markdown=True,  
)

# ---------------------------------------------------------------------------
# Dependent Agents
# ---------------------------------------------------------------------------
activities_agent = Agent(
    name="Activities Curator",
    model=Nvidia(id="meta/llama-3.3-70b-instruct"),
    tools=[WebSearchTools(backend="google"), TavilyTools()],
    instructions=[
        "You are an activities and experiences curator.",
        "Produce day-wise, bookable activities, not generic lists.",
        "Using `destination`, `interests_activities`, `travel_style`, `travel_companions`, and `travel_purpose`:",
        "- Curate a list of activities and experiences matching the user's `interests_activities`.",
        "- Tailor suggestions to `travel_companions` (kid-friendly, romantic, group-friendly).",
        "- Include estimated costs per activity and factor in the overall `budget`.",
        "- Organize activities by day considering weather research from the Weather Specialist.",
        "- Balance must-see attractions with off-the-beaten-path experiences based on `travel_style`.",
        "- Output as day-by-day blocks with time slot, activity, duration, cost, and booking note.",
    ],
    db=InMemoryDb(),
    markdown=True,
)

local_insider = Agent(
    name="Local Insider",
    model=Nvidia(id="meta/llama-3.3-70b-instruct"),
    tools=[WebSearchTools(backend="google"), TavilyTools()],
    tool_call_limit=10,
    instructions=[
        "You are a local insider and cultural advisor.",
        "Provide practical, place-specific recommendations only.",
        "Using `destination`, `interests_activities`, `travel_style`, and `travel_purpose`:",
        "- Share hidden gems, local favorites, and insider tips not found in typical guides.",
        "- Recommend local restaurants, street food, and dining experiences within `budget`.",
        "- Provide cultural do's and don'ts specific to the destination.",
        "- Suggest the best local experiences for the user's `travel_companions` type.",
        "- Include practical tips: tipping customs, bargaining, local apps to download.",
        "- Output as: hidden gems, food picks, etiquette notes, and traveler hacks with areas and price ranges.",
    ],
    db=InMemoryDb(),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Analysis Agents
# ---------------------------------------------------------------------------
budget_agent = Agent(
    name="Budget Optimizer",
    model=Nvidia(id="meta/llama-3.3-70b-instruct"),
    tools=[WebSearchTools(backend="google"), YFinanceTools(), convert_currency],
    instructions=[
        "You are a travel budget optimization specialist.",
        "Always produce a full numeric budget, never generic money-saving advice only.",
        "Using `budget`, `budget_flexibility`, `duration`, `travel_style`, and all cost data from other agents:",
        "- Create a detailed budget breakdown: flights, accommodation, transport, activities, food, misc.",
        "- Identify money-saving opportunities without sacrificing the `travel_style`.",
        "- If total exceeds `budget`, suggest trade-offs based on `budget_flexibility`.",
        "- Provide a 'strict budget' plan and an 'optimal experience' plan if flexibility allows.",
        "- Include a contingency/emergency fund recommendation.",
        "- Prefer the `convert_currency` tool for currency conversion.",
        "- If `convert_currency` fails, fall back to YFinanceTools (e.g. USDEUR=X forex pairs).",
        "- Output format must include: assumptions, line-item table, totals, gap vs budget, and final recommendation.",
        "- Include a validated cost table with subtotal checks.",
        "- Subtotals must sum to the grand total exactly.",
        "- Show arithmetic checks explicitly (e.g., flights + stay + local transport + activities + food + misc = total).",
    ],
    db=InMemoryDb(),
    markdown=True,
)

booking_agent = Agent(
    name="Booking Assistant",
    model=Nvidia(id="meta/llama-3.3-70b-instruct"),
    tools=[WebSearchTools()],
    instructions=[
        "You are a booking and itinerary compilation specialist.",
        "Your output is the final answer shown to the user. It must be a complete, structured travel plan.",
        "Do not return generic tips, high-level strategy lists, or placeholders.",
        "Using all research from other agents and the full travel request parameters:",
        "- Compile a day-by-day itinerary for the entire `duration`.",
        "- Include specific booking recommendations with timing and estimated costs.",
        "- Provide a prioritized booking order (flights first, then accommodation, then activities).",
        "- Add practical logistics: check-in/out times, transfer times between locations.",
        "- Create a summary checklist of all bookings needed with deadlines.",
        "- If any critical detail is missing, make a clearly labeled assumption and continue.",
        "- Include at least 3 named stay options and at least 2 named transport choices in the final output.",
        "- Budget section must include a validated cost table with explicit subtotal checks.",
        "- Booking timeline must include exact calendar dates derived from `travel_dates` (not generic '2 months before').",
        "- Final response structure must be:",
        "  1) Trip Summary",
        "  2) Day-by-Day Itinerary (morning/afternoon/evening with estimated costs)",
        "  3) Accommodation Plan",
        "  4) Transportation Plan",
        "  5) Budget Breakdown (totals + remaining budget/overrun)",
        "  6) Booking Priority Timeline",
        "  7) Packing + Local Tips",
        "  8) Final Checklist",
    ],
    db=InMemoryDb(),
    markdown=True,
)

# ---------------------------------------------------------------------------
# Workflow — input_schema goes HERE
# ---------------------------------------------------------------------------
travel_workflow = Workflow(
    name="Travel Planner",
    description="Multi-agent travel planning pipeline",
    input_schema=TravelRequest,  # <-- Validated at workflow level
    steps=[
        Parallel(
            Step(name="Weather Research", agent=weather_agent),
            Step(name="Destination Research", agent=destination_agent),
            Step(name="Accommodation Research", agent=accommodation_agent),
            Step(name="Transport Research", agent=transport_agent),
            name="Independent Research",
        ),
        Step(name="Activities Curation", agent=activities_agent),
        Step(name="Local Insights", agent=local_insider),
        Step(name="Budget Optimization", agent=budget_agent),
        Step(name="Final Itinerary", agent=booking_agent),
    ],
    db=db,
)

agent_os = AgentOS(
    workflows=[travel_workflow],
    agents=[
        weather_agent,
        destination_agent,
        accommodation_agent,
        transport_agent,
        activities_agent,
        local_insider,
        budget_agent,
        booking_agent,
    ],
)
app = agent_os.get_app()

if __name__ == "__main__":
    agent_os.serve(app="travel_planner:app", reload=True)
