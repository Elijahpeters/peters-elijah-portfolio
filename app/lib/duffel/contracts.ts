export type DuffelMode = "test" | "live";

export type DuffelApiEnvelope<T> = {
  data: T;
  meta?: unknown;
};

export type DuffelApiErrorEnvelope = {
  errors?: Array<{
    code?: unknown;
    title?: unknown;
    message?: unknown;
    type?: unknown;
  }>;
};

export type DuffelAirport = {
  iata_code?: unknown;
  name?: unknown;
  city_name?: unknown;
  iata_country_code?: unknown;
  time_zone?: unknown;
  latitude?: unknown;
  longitude?: unknown;
};

export type DuffelAirline = {
  iata_code?: unknown;
  name?: unknown;
  logo_symbol_url?: unknown;
  conditions_of_carriage_url?: unknown;
};

export type DuffelBaggage = {
  type?: unknown;
  quantity?: unknown;
};

export type DuffelSegmentPassenger = {
  passenger_id?: unknown;
  cabin_class?: unknown;
  cabin_class_marketing_name?: unknown;
  cabin?: {
    name?: unknown;
    marketing_name?: unknown;
  } | null;
  baggages?: unknown;
};

export type DuffelStop = {
  id?: unknown;
  airport?: unknown;
  arriving_at?: unknown;
  departing_at?: unknown;
  duration?: unknown;
};

export type DuffelSegment = {
  id?: unknown;
  origin?: unknown;
  destination?: unknown;
  departing_at?: unknown;
  arriving_at?: unknown;
  duration?: unknown;
  distance?: unknown;
  origin_terminal?: unknown;
  destination_terminal?: unknown;
  marketing_carrier?: unknown;
  operating_carrier?: unknown;
  marketing_carrier_flight_number?: unknown;
  operating_carrier_flight_number?: unknown;
  aircraft?: unknown;
  passengers?: unknown;
  stops?: unknown;
};

export type DuffelSlice = {
  id?: unknown;
  origin?: unknown;
  destination?: unknown;
  duration?: unknown;
  segments?: unknown;
};

export type DuffelCondition = {
  allowed?: unknown;
  penalty_amount?: unknown;
  penalty_currency?: unknown;
};

export type DuffelOffer = {
  id?: unknown;
  live_mode?: unknown;
  partial?: unknown;
  expires_at?: unknown;
  created_at?: unknown;
  updated_at?: unknown;
  total_amount?: unknown;
  total_currency?: unknown;
  base_amount?: unknown;
  base_currency?: unknown;
  tax_amount?: unknown;
  tax_currency?: unknown;
  total_emissions_kg?: unknown;
  owner?: unknown;
  slices?: unknown;
  passengers?: unknown;
  conditions?: {
    change_before_departure?: unknown;
    refund_before_departure?: unknown;
  } | null;
  passenger_identity_documents_required?: unknown;
  supported_passenger_identity_document_types?: unknown;
  payment_requirements?: {
    price_guarantee_expires_at?: unknown;
    payment_required_by?: unknown;
  } | null;
};

export type DuffelOfferRequest = {
  id?: unknown;
  live_mode?: unknown;
  offers?: unknown;
};
