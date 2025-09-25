#!/usr/bin/env python3
"""
SEC Historical Data Loader
Downloads and parses real Form 4 insider trading data from SEC EDGAR for backtesting.
"""

import logging
import time
import json
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
import requests
import re
from dataclasses import asdict

from database_manager import InsiderFiling

class SECHistoricalLoader:
    """Loads real historical insider trading data from SEC for backtesting"""

    def __init__(self, user_agent: str = None, db_manager=None):
        """Initialize historical data loader"""
        self.logger = logging.getLogger(__name__)
        self.db_manager = db_manager  # Optional database manager for URL caching

        # SEC API configuration
        self.user_agent = user_agent or "InsideTracker admin@gmail.com"
        self.request_delay = 0.1  # 100ms delay between requests

        # Complete target companies mapping (all 36 companies across all tiers)
        self.target_companies = {
            # Tier 1: Mega-caps
            'AAPL': '0000320193',    # Apple Inc
            'NVDA': '0001045810',    # NVIDIA Corp
            'MSFT': '0000789019',    # Microsoft Corp
            'GOOGL': '0001652044',   # Alphabet Inc Class A
            'AMZN': '0001018724',    # Amazon.com Inc
            'META': '0001326801',    # Meta Platforms Inc
            'TSLA': '0001318605',    # Tesla Inc

            # Tier 2: Large-caps
            'JPM': '0000019617',     # JPMorgan Chase & Co
            'JNJ': '0000200406',     # Johnson & Johnson
            'V': '0001403161',       # Visa Inc
            'PG': '0000080424',      # Procter & Gamble Co
            'UNH': '0000731766',     # UnitedHealth Group Inc
            'HD': '0000354950',      # Home Depot Inc
            'MA': '0001141391',      # Mastercard Inc
            'DIS': '0001001039',     # Walt Disney Co
            'NFLX': '0001065280',    # Netflix Inc
            'CRM': '0001108524',     # Salesforce Inc

            # Tier 3: Mid-caps + Quality
            'DDOG': '0001561550',    # Datadog Inc
            'ZS': '0001713683',      # Zscaler Inc
            'CRWD': '0001535527',    # CrowdStrike Holdings Inc
            'TEAM': '0001650372',    # Atlassian Corp
            'ALGN': '0001097149',    # Align Technology Inc
            'ROKU': '0001428439',    # Roku Inc
            'ADBE': '0000796343',    # Adobe Inc
            'PFE': '0000078003',     # Pfizer Inc
            'KO': '0000021344',      # Coca-Cola Co
            'TMO': '0000097745',     # Thermo Fisher Scientific Inc
            'ABT': '0000001800',     # Abbott Laboratories

            # Tier 4: Small-cap Sandbox
            'PLTR': '0001321655',    # Palantir Technologies Inc
            'RBLX': '0001315098',    # Roblox Corp
            'FUBO': '0001507230',    # FuboTV Inc
            'SOFI': '0001818874',    # SoFi Technologies Inc
            'OPEN': '0001518715',    # Opendoor Technologies Inc
            'COIN': '0001679788',    # Coinbase Global Inc
            'HOOD': '0001783879',    # Robinhood Markets Inc
            'LCID': '0001811210'     # Lucid Group Inc
        }

    def _rate_limited_request(self, url: str) -> Optional[requests.Response]:
        """Make rate-limited request to SEC API"""
        try:
            headers = {'User-Agent': self.user_agent}
            time.sleep(self.request_delay)  # Rate limiting
            response = requests.get(url, headers=headers, timeout=30)
            response.raise_for_status()
            return response
        except Exception as e:
            self.logger.error(f"Request failed for {url}: {e}")
            return None

    def load_historical_data(self, start_date: str, end_date: str,
                           companies: List[str] = None) -> List[InsiderFiling]:
        """
        Load real historical insider trading data for specified date range

        Args:
            start_date: Start date in YYYY-MM-DD format
            end_date: End date in YYYY-MM-DD format
            companies: List of ticker symbols (default: all target companies)

        Returns:
            List of InsiderFiling objects with real transaction data
        """
        if companies is None:
            companies = list(self.target_companies.keys())

        self.logger.info(f"🔍 Loading historical insider data:")
        self.logger.info(f"   Date range: {start_date} to {end_date}")
        self.logger.info(f"   Companies: {companies}")

        all_filings = []

        for ticker in companies:
            if ticker not in self.target_companies:
                self.logger.warning(f"Unknown ticker {ticker}, skipping")
                continue

            cik = self.target_companies[ticker]
            self.logger.info(f"📊 Processing {ticker} (CIK: {cik})...")

            # Get company's Form 4 filings
            company_filings = self._get_company_form4_history(cik, start_date, end_date)

            # Parse each filing to extract real transaction details
            for filing_metadata in company_filings:
                try:
                    parsed_filings = self._parse_form4_document(filing_metadata, ticker)
                    all_filings.extend(parsed_filings)

                except Exception as e:
                    self.logger.warning(f"Error parsing filing {filing_metadata.get('accession_number', 'unknown')}: {e}")
                    continue

        self.logger.info(f"✅ Loaded {len(all_filings)} real insider transactions")
        return all_filings

    def _get_company_form4_history(self, cik: str, start_date: str, end_date: str) -> List[Dict]:
        """Get Form 4 filing metadata for company in date range"""
        try:
            # Get company's complete filing history
            url = f"https://data.sec.gov/submissions/CIK{cik.zfill(10)}.json"
            response = self._rate_limited_request(url)

            if not response:
                return []

            data = response.json()
            recent_filings = data.get('filings', {}).get('recent', {})

            if not recent_filings:
                return []

            # Extract Form 4 filings in date range
            forms = recent_filings.get('form', [])
            filing_dates = recent_filings.get('filingDate', [])
            accession_numbers = recent_filings.get('accessionNumber', [])
            primary_docs = recent_filings.get('primaryDocument', [])

            filtered_filings = []

            for i, form in enumerate(forms):
                if form == '4' and i < len(filing_dates):
                    filing_date = filing_dates[i]

                    # Check if filing is in our target date range
                    if start_date <= filing_date <= end_date:
                        filing_info = {
                            'form': form,
                            'cik': cik,
                            'filing_date': filing_date,
                            'accession_number': accession_numbers[i] if i < len(accession_numbers) else '',
                            'primary_document': primary_docs[i] if i < len(primary_docs) else '',
                            'document_url': self._build_document_url(cik, accession_numbers[i], primary_docs[i]) if i < len(accession_numbers) and i < len(primary_docs) else ''
                        }
                        filtered_filings.append(filing_info)

            self.logger.info(f"   Found {len(filtered_filings)} Form 4 filings in date range")
            return filtered_filings

        except Exception as e:
            self.logger.error(f"Error getting Form 4 history for CIK {cik}: {e}")
            return []

    def _build_document_url(self, cik: str, accession_number: str, document_name: str) -> str:
        """Build URL for Form 4 document"""
        clean_accession = accession_number.replace('-', '')

        # For now, try the primary document URL directly
        # We'll handle XML parsing issues in the next step
        return f"https://www.sec.gov/Archives/edgar/data/{cik}/{clean_accession}/{document_name}"

    def _parse_form4_document(self, filing_metadata: Dict, ticker: str) -> List[InsiderFiling]:
        """
        Parse Form 4 document to extract real transaction details
        This is where we'll implement real XML parsing (Phase 1: basic structure)
        """
        try:
            document_url = filing_metadata.get('document_url', '')
            if not document_url:
                return []

            # URL caching: Skip if already processed (prevents redundant parsing)
            if self.db_manager and self.db_manager.is_document_url_processed(document_url):
                self.logger.info(f"   📋 Skipping already processed URL: {document_url}")
                return []

            self.logger.info(f"   📄 Attempting to parse: {document_url}")

            # Use index.json approach to find raw XML documents
            raw_xml_documents = self._find_raw_form4_xml(filing_metadata)

            for xml_url in raw_xml_documents:
                self.logger.info(f"      📄 Trying raw XML: {xml_url}")

                response = self._rate_limited_request(xml_url)
                if not response:
                    continue

                # Check if we got actual XML
                content_preview = response.text[:200] if response.text else ""
                if content_preview.strip().startswith('<?xml'):
                    self.logger.info(f"      ✅ Found raw XML content")
                    # Try to parse real XML content
                    parsed_filings = self._parse_form4_xml(response.text, filing_metadata, ticker)
                    if parsed_filings:
                        # Cache successful parsing with transactions
                        if self.db_manager:
                            self.db_manager.cache_processed_document_url(
                                document_url, ticker, 'transactions_found', len(parsed_filings)
                            )
                        return parsed_filings
                    else:
                        self.logger.info(f"      📋 XML parsed successfully, but no qualifying transactions found for {ticker}")
                        # Cache successful parsing but no qualifying transactions
                        if self.db_manager:
                            self.db_manager.cache_processed_document_url(
                                document_url, ticker, 'no_transactions', 0
                            )
                        return []
                else:
                    self.logger.info(f"      ❌ Not XML content: {content_preview[:50]}...")

            # Only reach here if no XML files found or all failed to parse
            self.logger.warning(f"      ❌ No valid XML content found for {ticker}")
            # Cache parse error
            if self.db_manager:
                self.db_manager.cache_processed_document_url(
                    document_url, ticker, 'parse_error', 0
                )
            return []

        except Exception as e:
            self.logger.error(f"Error parsing Form 4 document: {e}")
            # Cache parse error
            if self.db_manager:
                self.db_manager.cache_processed_document_url(
                    document_url, ticker, 'parse_error', 0
                )
            return []


    def _find_raw_form4_xml(self, filing_metadata: Dict) -> List[str]:
        """
        Find raw Form 4 XML documents using SEC index.json approach
        Based on SEC documentation for directory structure
        """
        try:
            cik = filing_metadata.get('cik', '')
            accession_number = filing_metadata.get('accession_number', '')

            if not cik or not accession_number:
                return []

            # Build directory URL (without leading zeros in CIK)
            clean_cik = cik.lstrip('0') or '0'
            clean_accession = accession_number.replace('-', '')

            # Get index.json for the filing directory
            index_url = f"https://www.sec.gov/Archives/edgar/data/{clean_cik}/{clean_accession}/index.json"
            self.logger.info(f"      📂 Checking directory index: {index_url}")

            response = self._rate_limited_request(index_url)
            if not response:
                return []

            index_data = response.json()

            # Debug: Log what we find in the directory
            self.logger.info(f"      📋 Directory structure: {list(index_data.keys())}")

            # Look for Form 4 XML documents in the directory listing
            xml_urls = []

            if 'directory' in index_data and 'item' in index_data['directory']:
                items = index_data['directory']['item']
                self.logger.info(f"      📂 Found {len(items)} items in directory")

                # Debug: Print the entire structure
                for item in items:
                    item_type = item.get('type', 'unknown')
                    filename = item.get('name', 'no-name')
                    self.logger.info(f"      📋 Item: {filename} (type: {item_type})")

                    # Look for XML files regardless of reported type (SEC reports all as text.gif)
                    if filename.endswith('.xml'):
                        xml_url = f"https://www.sec.gov/Archives/edgar/data/{clean_cik}/{clean_accession}/{filename}"
                        xml_urls.append(xml_url)
                        self.logger.info(f"      ✅ XML candidate: {filename}")

            # If no XML found from index, try the original primary document URL
            if not xml_urls:
                # Try the primary document that was originally listed
                primary_doc = filing_metadata.get('primary_document', '')
                if primary_doc:
                    primary_url = f"https://www.sec.gov/Archives/edgar/data/{clean_cik}/{clean_accession}/{primary_doc}"
                    xml_urls.append(primary_url)
                    self.logger.info(f"      📋 Trying primary document: {primary_doc}")

                # Also try common patterns
                common_patterns = ['doc4.xml', 'form4.xml', f'{accession_number}.xml']
                for pattern in common_patterns:
                    test_url = f"https://www.sec.gov/Archives/edgar/data/{clean_cik}/{clean_accession}/{pattern}"
                    xml_urls.append(test_url)

            return xml_urls

        except Exception as e:
            self.logger.error(f"Error finding raw Form 4 XML: {e}")
            return []

    def _parse_form4_xml(self, xml_content: str, filing_metadata: Dict, ticker: str) -> List[InsiderFiling]:
        """
        Parse raw Form 4 XML to extract real transaction details
        This implements actual XML parsing for Phase 2
        """
        try:
            # Parse XML with namespace handling
            root = ET.fromstring(xml_content)

            # Debug: Log XML structure
            self.logger.info(f"      🔍 XML root tag: {root.tag}")
            self.logger.info(f"      🔍 XML namespace: {root.tag.split('}')[0] if '}' in root.tag else 'No namespace'}")
            self.logger.info(f"      🔍 Root children: {[child.tag for child in root][:5]}")  # First 5 children

            # Form 4 XML has namespaces - find the root element
            # Common namespaces in SEC Form 4 documents
            namespaces = {
                '': 'http://www.sec.gov/edgar/document/thirteenf/informationtable',
                'edgar': 'http://www.sec.gov/edgar/common',
                'xsi': 'http://www.w3.org/2001/XMLSchema-instance'
            }

            filings = []
            cik = filing_metadata.get('cik', '')
            filing_date = filing_metadata.get('filing_date', '')
            accession_number = filing_metadata.get('accession_number', '')

            # Extract issuer information from 'issuer' element
            issuer_name = ticker  # Fallback
            issuer_elem = root.find('issuer')
            if issuer_elem is not None:
                issuer_name_elem = issuer_elem.find('issuerName')
                if issuer_name_elem is not None and issuer_name_elem.text:
                    issuer_name = issuer_name_elem.text

            # Extract reporting owner (insider) information
            insider_name = "Unknown Insider"
            insider_title = "Unknown Title"

            reporting_owner = root.find('reportingOwner')
            if reporting_owner is not None:
                # Get owner identity
                owner_id = reporting_owner.find('reportingOwnerId')
                if owner_id is not None:
                    name_elem = owner_id.find('rptOwnerName')
                    if name_elem is not None and name_elem.text:
                        insider_name = name_elem.text

                # Get owner relationship (title)
                owner_relationship = reporting_owner.find('reportingOwnerRelationship')
                if owner_relationship is not None:
                    title_elem = owner_relationship.find('officerTitle')
                    if title_elem is not None and title_elem.text:
                        insider_title = title_elem.text
                    elif owner_relationship.find('isDirector') is not None and owner_relationship.find('isDirector').text == '1':
                        insider_title = "Director"
                    elif owner_relationship.find('isOfficer') is not None and owner_relationship.find('isOfficer').text == '1':
                        insider_title = "Officer"

            self.logger.info(f"      👤 Found insider: {insider_name} ({insider_title})")

            # Extract non-derivative transactions (most common)
            transactions_found = 0
            for transaction in root.findall('.//nonDerivativeTransaction'):

                    transactions_found += 1
                    self.logger.info(f"      📊 Processing transaction #{transactions_found}")

                    # Extract transaction details using correct Form 4 structure
                    transaction_date = filing_date  # Fallback
                    transaction_code = 'P'  # Default to Purchase
                    shares_traded = 0.0
                    price_per_share = 0.0
                    ownership_type = 'D'  # Direct ownership
                    shares_owned_after = 0.0

                    # Get transaction date
                    trans_date_elem = transaction.find('transactionDate/value')
                    if trans_date_elem is not None and trans_date_elem.text:
                        transaction_date = trans_date_elem.text

                    # Get transaction code
                    trans_code_elem = transaction.find('transactionCoding/transactionCode')
                    if trans_code_elem is not None and trans_code_elem.text:
                        transaction_code = trans_code_elem.text

                    # Get transaction amounts
                    trans_amounts = transaction.find('transactionAmounts')
                    if trans_amounts is not None:
                        # Get shares traded
                        shares_elem = trans_amounts.find('transactionShares/value')
                        if shares_elem is not None and shares_elem.text:
                            try:
                                shares_traded = float(shares_elem.text.replace(',', ''))
                            except ValueError:
                                pass

                        # Get price per share
                        price_elem = trans_amounts.find('transactionPricePerShare/value')
                        if price_elem is not None and price_elem.text:
                            try:
                                price_per_share = float(price_elem.text.replace(',', '').replace('$', ''))
                            except ValueError:
                                pass

                    # Get ownership type
                    ownership_elem = transaction.find('ownershipNature/directOrIndirectOwnership/value')
                    if ownership_elem is not None and ownership_elem.text:
                        ownership_type = ownership_elem.text

                    # Get shares owned after transaction
                    owned_after_elem = transaction.find('postTransactionAmounts/sharesOwnedFollowingTransaction/value')
                    if owned_after_elem is not None and owned_after_elem.text:
                        try:
                            shares_owned_after = float(owned_after_elem.text.replace(',', ''))
                        except ValueError:
                            pass

                    self.logger.info(f"      💰 Transaction: {transaction_code} {shares_traded:,.0f} shares @ ${price_per_share:.2f}")

                    # Apply insider trading strategy filters
                    total_value = shares_traded * price_per_share

                    # Filter 1: Only Purchase transactions (exclude gifts, options, etc.)
                    if transaction_code != 'P':
                        self.logger.info(f"      ⏭️ Skipping non-purchase transaction: {transaction_code} (we only track purchases 'P')")
                        continue

                    # Filter 2: Minimum transaction value ($50k filter)
                    if total_value < 50000:
                        self.logger.info(f"      ⏭️ Skipping small transaction: ${total_value:,.0f} (minimum: $50,000)")
                        continue

                    # Transaction meets all criteria - include it
                    self.logger.info(f"      ✅ Transaction qualifies: {transaction_code} ${total_value:,.0f}")

                    filing_id = f"REAL_XML_{ticker}_{insider_name.replace(' ', '_')}_{transaction_date}_{accession_number}"
                    filing_id = re.sub(r'[^\w\-_.]', '', filing_id)

                    filing = InsiderFiling(
                        filing_id=filing_id,
                        company_symbol=ticker,
                        company_name=issuer_name,
                        company_cik=cik,
                        insider_name=insider_name,
                        insider_title=insider_title,
                        transaction_date=transaction_date,
                        transaction_code=transaction_code,
                        shares_traded=shares_traded,
                        price_per_share=round(price_per_share, 2),
                        total_value=round(total_value, 2),
                        ownership_type=ownership_type,
                        shares_owned_after=shares_owned_after,
                        filing_date=filing_date,
                        is_first_time_purchase=False,
                        raw_filing_data=json.dumps({
                            'source': 'sec_historical_real_xml_parsed',
                            'accession_number': accession_number,
                            'xml_content_length': len(xml_content),
                            'phase': 'Phase_2_real_xml_parsing'
                        })
                    )

                    filings.append(filing)
                    self.logger.info(f"      ✅ Parsed transaction: {transaction_code} {shares_traded:,.0f} shares @ ${price_per_share:.2f}")

            return filings

        except ET.ParseError as e:
            self.logger.error(f"XML parsing error: {e}")
            return []
        except Exception as e:
            self.logger.error(f"Error parsing Form 4 XML: {e}")
            return []

def main():
    """Test the historical data loader"""
    import os
    from dotenv import load_dotenv

    load_dotenv()

    # Setup logging
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
    )

    # Initialize loader
    user_agent = os.getenv('SEC_USER_AGENT', 'Sample Company Name AdminContact@<sample company domain>.com')
    loader = SECHistoricalLoader(user_agent)

    # Test with 2 days of data for PoC
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=2)).strftime('%Y-%m-%d')

    print(f"🚀 Testing SEC Historical Data Loader")
    print(f"📅 Date range: {start_date} to {end_date}")

    # Load real historical data
    filings = loader.load_historical_data(start_date, end_date)

    print(f"\n📊 Results:")
    print(f"   Total filings loaded: {len(filings)}")

    if filings:
        print(f"\n📋 Sample filing:")
        sample = filings[0]
        print(f"   Company: {sample.company_symbol}")
        print(f"   Insider: {sample.insider_name} ({sample.insider_title})")
        print(f"   Transaction: {sample.transaction_code} {sample.shares_traded:,.0f} shares @ ${sample.price_per_share:.2f}")
        print(f"   Total Value: ${sample.total_value:,.0f}")
        print(f"   Date: {sample.transaction_date}")
        print(f"   Filing ID: {sample.filing_id}")

if __name__ == "__main__":
    main()