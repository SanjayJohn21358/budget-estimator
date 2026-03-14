"""Configuration classes for the Budget Estimator app."""

from pydantic import Field
from pydantic_settings import BaseSettings


class SheetConfig(BaseSettings):
    """Google Sheets configuration."""

    pricing_guide_sheet_id: str = Field(
        default="",
        description="Google Sheet ID for the pricing guide",
    )
    output_template_sheet_id: str = Field(
        default="",
        description="Google Sheet ID for the output template",
    )
    pricing_guide_tab_name: str = Field(
        default="Sheet1",
        description="Tab name within the pricing guide sheet",
    )
    output_template_tab_name: str = Field(
        default="Sheet1",
        description="Tab name within the output template sheet",
    )
    estimates_sheet_id: str = Field(
        default="",
        description=(
            "Google Sheet ID for the shared estimates workbook. "
            "Each export adds a new tab here instead of creating a new file."
        ),
    )

    model_config = {"env_prefix": "SHEET_"}


class CostConfig(BaseSettings):
    """Cost-related constants that the user can tune."""

    dump_run_cost: float = Field(
        default=120.0,
        description="Cost per dump run in dollars",
    )
    labor_rate_per_hour: float = Field(
        default=60.0,
        description="Labor rate per hour in dollars",
    )
    crew_size: int = Field(
        default=2,
        description="Number of people in the crew",
    )
    plant_delivery_pct: float = Field(
        default=0.07,
        description="Plant delivery cost as a percentage of plant total",
    )
    tax_rate: float = Field(
        default=0.0875,
        description="Sales tax rate",
    )

    model_config = {"env_prefix": "COST_"}


class LLMConfig(BaseSettings):
    """LLM service configuration."""

    openai_api_key: str = Field(
        default="",
        description="OpenAI API key",
    )
    model_name: str = Field(
        default="gpt-4o",
        description="LLM model to use for text interpretation",
    )
    temperature: float = Field(
        default=0.2,
        description="LLM temperature (lower = more deterministic)",
    )
    system_prompt: str = Field(
        default=(
            "You are a landscaping project estimator assistant. "
            "You help translate project descriptions into structured cost estimates. "
            "You must ONLY use materials that exist in the provided pricing guide. "
            "If the description mentions something not in the guide, flag it. "
            "Always respond with valid JSON matching the requested schema."
        ),
        description="Base system prompt for the LLM",
    )

    model_config = {"env_prefix": "LLM_"}


class AppConfig(BaseSettings):
    """General application configuration."""

    app_title: str = Field(
        default="Landscaping Budget Estimator",
        description="Title displayed in the app",
    )
    access_levels: list[str] = Field(
        default=["Easy", "Medium", "Difficult"],
        description="Available access level options",
    )
    default_line_items: list[str] = Field(
        default=[
            "Arbor",
            "Arbor Mulch",
            "Awning",
            "Backflow preventer assembly",
            "Basalt Rock",
            "Base Layer",
            "Base Rock",
            "Bench",
            "Brick Demo/Hauling",
            "Brush",
            "Bulk Materials",
            "Cedar Trellis",
            "Chainsaw",
            "Chicken Coop",
            "Citrus Fertilizer",
            "Clay Pots",
            "Clay saucer",
            "Cleanup/Prep",
            "Compost Bin",
            "Compression Ell",
            "Compression Tee",
            "Concrete",
            "Concrete (60 lb)",
            "Concrete Pad",
            "Concrete Sand",
            "Connections, Fittings, Fasteners, Hardware",
            "Consulting",
            "Copper Fungicide",
            "Copper Gutters",
            "Cork mats",
            "Custom Planters",
            "Deck",
            "Decomposed Granite",
            "Decorative Rock",
            "Delivery Fee",
            "Demo/Hauling",
            "Deposit",
            "Dig Irrigation controller",
            "Discount",
            "Dog Run",
            "Dog Zone",
            "Drain",
            "Drainage",
            "Drain Rock",
            "Driveway",
            "Drop-in Stainless Steel Basin (2 tub)",
            "Dry Creekbed",
            "Edging",
            "Electrical Work",
            "Facade",
            "Fan Espalier",
            "Faucet Assembly",
            "Faucet Connection Hose",
            "Fence",
            "Fertilizer",
            "Fertillizer",
            "Firepit",
            "Flagstone",
            "Food Grade Hose",
            "Foundation",
            "Front Area",
            "Fruit Tree Fertilizer",
            "Galvanized Drain Tank",
            "Galvanized Screws",
            "Garbage Bin Enclosure",
            "Garden Hose 50'",
            "Gas Line",
            "Gate",
            "Goof Plug 10 Pack",
            "Gopher Cage",
            "Gopher Cage 15 gal",
            "Gopher Cage 1 gal",
            "Gopher Cage 5 gal",
            "Grass area",
            "Grass seed",
            "Graywater",
            "Greenhouse",
            "Greywater Kit",
            "Ground Cover",
            "Guardrail",
            "Hacksaw 10\" blade",
            "Handrails",
            "Hardware cloth",
            "Herb Spiral",
            "Hose Nozzle",
            "Hours",
            "Indoor Pots",
            "Interactive Elements",
            "Landscape Fabric",
            "Landscape Spikes",
            "Landscape Stairs",
            "Landscape Staples",
            "Landscaping:Calstone Permeable Quarry",
            "Landscaping:Construction/Hardscaping",
            "Landscaping:Consultation/Research/Design",
            "Landscaping:General",
            "Landscaping:Hauling Removal",
            "Landscaping:Project Management",
            "Landscaping:Soil/Amendments",
            "Landscaping:Supplies",
            "Landscaping:Trees & Shrubs",
            "Lattice",
            "Lighting",
            "Living Wall",
            "Logiscape Design",
            "Logiscape Light  Design",
            "Lumber",
            "Maintenance:Garden Maintenance",
            "Marketing",
            "Material Bags",
            "Materials",
            "Metal Landscape Edging",
            "Metal Stake Bundle",
            "Mileage",
            "Mini Mulch",
            "Miscellaneous",
            "Mulch",
            "Mulch Delivery",
            "Mulched Beds",
            "Neem Oil Fungicide",
            "Olympia Sand",
            "Outdoor Kitchen",
            "Outdoor Pots",
            "Outdoor Shower",
            "Owl Box",
            "Pathway",
            "Patio",
            "Pavers",
            "Payment",
            "PE 100' roll",
            "Pea Gravel",
            "Performance",
            "Pergola",
            "Permitting",
            "Plant Delivery",
            "Planters",
            "Plants",
            "Platform",
            "Play Area",
            "Playground Chips",
            "Play Structure",
            "Porta Potty Rental",
            "Pottery",
            "Potting Soil",
            "PVC Misc.",
            "Railing",
            "Raised Beds",
            "Redwood screen",
            "Refund",
            "Reimbursable Expense",
            "Reimbursable Expense Item",
            "Resurface Retaining Wall",
            "Retainer",
            "Retaining Feature",
            "Retaining Wall",
            "Roof Gravel",
            "Royalty",
            "Sales",
            "Sand Box",
            "Sandpaper",
            "Sauna",
            "Screening",
            "Services",
            "Shed",
            "Sheet Mulch",
            "Shipping",
            "Silicone Caulk",
            "Sitting Area",
            "Sod",
            "Soil Removal",
            "Soil Test",
            "Sonic Spike",
            "Spray Nozzle",
            "Stairs",
            "Stake",
            "Stepping Stones",
            "Steps",
            "Stone",
            "Stone veneer",
            "Storage",
            "Strainer/Drain Assembly",
            "Stump Grinder",
            "Supplies",
            "Sure Start Fertilizer",
            "Tax:Sales Tax",
            "Test",
            "Tip",
            "Tool Rental",
            "Top Caps",
            "Topsoil",
            "Transfer Station",
            "Tree Box",
            "Tree Trim",
            "Trellis",
            "Turf",
            "Walkway",
            "Water Feature",
            "Water:Irrigation",
            "Water:Plumbing",
            "Weather Resistant Stand",
            "Weed Spray",
            "Wood Stain",
        ],
        description="Default line item categories (overridden by template sheet if available)",
    )

    model_config = {"env_prefix": "APP_"}

