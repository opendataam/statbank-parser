import requests
from bs4 import BeautifulSoup
import pandas as pd
from urllib.parse import urljoin, urlparse, parse_qs
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

class StatbankScraper:
    BASE_URL = "https://statbank.armstat.am/pxweb/en/ArmStatBank/"

    def __init__(self):
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
        })

    def get_indicators(self):
        """
        Traverses the category tree to find all tables.
        Returns a list of dictionaries with 'id', 'title', 'url', 'topic', 'subtopics'.
        """
        self.visited = set()
        return self._traverse_category(self.BASE_URL, [])

    def _traverse_category(self, url, breadcrumbs):
        if url in self.visited:
            return []
        self.visited.add(url)
        
        logger.info(f"Visiting category: {url}")
        items = []
        
        try:
            response = self.session.get(url)
            response.raise_for_status()
            soup = BeautifulSoup(response.content, 'html.parser')
            
            # Find the main content area
            content_area = soup.find('div', id='pxwebcontent')
            if not content_area:
                 # Fallback to body if specific container not found
                 logger.warning("Could not find pxwebcontent, using body")
                 content_area = soup.body

            links = content_area.find_all('a')
            logger.info(f"Found {len(links)} links in content area")
            
            for link in links:
                href = link.get('href', '')
                text = link.get_text(strip=True)
                # logger.info(f"Checking link: {text} -> {href}")
                
                if not href:
                    continue

                if href.lower().endswith('.px') or href.lower().endswith('.px/'):
                    # It's a table
                    full_url = urljoin(url, href)
                    
                    # Extract ID from URL
                    # Example: .../EF-NA-01.px/ -> EF-NA-01
                    path = urlparse(full_url).path
                    filename = path.split('/')[-1]
                    if not filename: # Handle trailing slash
                        filename = path.split('/')[-2]
                    
                    table_id = filename.replace('.px', '')
                    
                    # Topic is the first breadcrumb, subtopics are the rest
                    topic = breadcrumbs[0] if breadcrumbs else ""
                    subtopics = breadcrumbs[1:] if len(breadcrumbs) > 1 else []

                    items.append({
                        'id': table_id,
                        'title': text,
                        'url': full_url,
                        'topic': topic,
                        'subtopics': subtopics
                    })
                elif 'javascript:__doPostBack' in href:
                    # Parse PostBack to construct URL
                    try:
                        args = href.split("'")
                        if len(args) >= 4:
                            target = args[1]
                            argument = args[3]
                            
                            # We only care about navigation tree postbacks
                            if 'MenuNavigationTree' in target:
                                # The argument is like: pArmStatBank__1 ...\\ArmStatBank__1 ...
                                # We take the last part
                                parts = argument.split('\\\\') # It's escaped in JS, so might be \\ or \
                                if len(parts) == 1:
                                     parts = argument.split('\\')
                                
                                last_part = parts[-1]
                                
                                # Remove leading 'p' if it exists (seems to be a prefix for nodes)
                                # But be careful, 'p' might be part of the name? 
                                # Looking at examples: 'pArmStatBank__1...' -> 'ArmStatBank__1...'
                                # So yes, remove first char if it is 'p' and the rest matches the pattern
                                if last_part.startswith('p') and 'ArmStatBank' in last_part:
                                     last_part = last_part[1:]
                                
                                # Construct new URL
                                # The base seems to be constant: https://statbank.armstat.am/pxweb/en/ArmStatBank/
                                # And we append the node ID.
                                # Wait, the node ID is the full path?
                                # Example: ArmStatBank__1 Econnomy and finance__15 National Accounts
                                # Yes, it seems to be the full path relative to ArmStatBank/
                                
                                # URL Encode
                                import urllib.parse
                                encoded_part = urllib.parse.quote(last_part)
                                
                                new_url = f"https://statbank.armstat.am/pxweb/en/ArmStatBank/{encoded_part}"
                                
                                # Update breadcrumbs
                                # The text of the link is the new category name
                                new_breadcrumbs = breadcrumbs + [text]
                                
                                # Recurse
                                items.extend(self._traverse_category(new_url, new_breadcrumbs))
                    except Exception as e:
                        logger.warning(f"Failed to parse PostBack: {href} - {e}")
                elif 'ArmStatBank' in href and href.startswith('http'):
                     # It might be a direct link to a sub-category (like in the breadcrumbs or main list if they changed it)
                     # But we should be careful not to go back up (breadcrumbs)
                     # Breadcrumbs usually have distinct classes or IDs, but here we just check if it's longer?
                     pass

            return items

        except Exception as e:
            logger.error(f"Error traversing {url}: {e}")
            return []

    def get_available_formats(self, table_url):
        """
        Gets the list of available file formats for a table.
        Returns a list of format names.
        """
        logger.info(f"Fetching available formats for: {table_url}")
        
        # 1. Get the initial page
        response = self.session.get(table_url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        form = soup.find('form', id='aspnetForm')
        if not form:
            raise Exception("Could not find aspnetForm")

        viewstate = soup.find('input', id='__VIEWSTATE')['value']
        eventvalidation = soup.find('input', id='__EVENTVALIDATION')['value']
        
        data = {
            '__VIEWSTATE': viewstate,
            '__EVENTVALIDATION': eventvalidation,
        }
        
        button = soup.find('input', {'type': 'submit', 'value': 'Continue'})
        if not button:
             button = soup.find('input', {'type': 'submit', 'value': 'Show table'})
        if not button:
             button = soup.find('input', {'type': 'submit', 'class': 'pxweb-btn-action'})
        
        if button:
            data[button['name']] = button['value']
        else:
             # Fallback
             data['ctl00$ContentPlaceHolderMain$VariableSelector1$VariableSelector1$ButtonViewTable'] = 'Show table'

        # Select all options for each listbox
        selects = soup.find_all('select')
        for select in selects:
            name = select['name']
            options = [opt['value'] for opt in select.find_all('option')]
            data[name] = options
            
        # Post to get the result page
        post_response = self.session.post(table_url, data=data)
        post_response.raise_for_status()
        
        result_soup = BeautifulSoup(post_response.content, 'html.parser')
        
        # Find all format labels
        formats = []
        labels = result_soup.find_all('label')
        for label in labels:
            if 'SaveAsRadioButtonList' in label.get('for', ''):
                formats.append(label.get_text(strip=True))
        
        return formats

    def get_table_data(self, table_url, file_format=None):
        """
        Fetches data for a specific table URL.
        If file_format is provided, downloads the file in that format.
        Supported formats: 'excel', 'csv', 'json', 'px', etc. (matches text in dropdown)
        """
        logger.info(f"Fetching data for: {table_url} (Format: {file_format})")
        
        # 1. Get the initial page to extract ViewState and Options
        response = self.session.get(table_url)
        response.raise_for_status()
        soup = BeautifulSoup(response.content, 'html.parser')
        
        form = soup.find('form', id='aspnetForm')
        if not form:
            raise Exception("Could not find aspnetForm")

        viewstate = soup.find('input', id='__VIEWSTATE')['value']
        eventvalidation = soup.find('input', id='__EVENTVALIDATION')['value']
        
        data = {
            '__VIEWSTATE': viewstate,
            '__EVENTVALIDATION': eventvalidation,
        }
        
        button = soup.find('input', {'type': 'submit', 'value': 'Continue'})
        if not button:
             button = soup.find('input', {'type': 'submit', 'value': 'Show table'})
        if not button:
             button = soup.find('input', {'type': 'submit', 'class': 'pxweb-btn-action'})
        
        if button:
            data[button['name']] = button['value']
        else:
             data['ctl00$ContentPlaceHolderMain$VariableSelector1$VariableSelector1$ButtonViewTable'] = 'Show table'

        # Select all options for each listbox
        selects = soup.find_all('select')
        for select in selects:
            name = select['name']
            options = [opt['value'] for opt in select.find_all('option')]
            data[name] = options
            
        # 3. Post the form to get the table view
        post_response = self.session.post(table_url, data=data)
        post_response.raise_for_status()
        
        if not file_format:
            # Default behavior: Parse HTML table
            result_soup = BeautifulSoup(post_response.content, 'html.parser')
            table = result_soup.find('table', {'class': 'pxweb-table'})
            
            if not table:
                tables = pd.read_html(post_response.content)
                if tables:
                    return tables[0]
                else:
                    raise Exception("No table found in response")
            
            df = pd.read_html(str(table))[0]
            return df
        else:
            # Download specific format
            # We are now on the result page. We need to find the "Save as" options.
            result_soup = BeautifulSoup(post_response.content, 'html.parser')
            
            # Find the radio button list
            # Usually id ends with SaveAsRadioButtonList
            # We need to map the requested format to the radio button value
            
            # Debug: Log all inputs
            inputs = result_soup.find_all('input')
            for inp in inputs:
                logger.info(f"Input: name={inp.get('name')}, id={inp.get('id')}, value={inp.get('value')}")
            
            # Common mapping based on text
            # We'll try to find the label containing the requested format text
            labels = result_soup.find_all('label')
            target_value = None
            
            # Normalize format string
            fmt_lower = file_format.lower()
            
            for label in labels:
                label_text = label.get_text(strip=True).lower()
                if fmt_lower in label_text:
                    # Found a match, get the input ID
                    input_id = label.get('for')
                    if input_id:
                        inp = result_soup.find('input', id=input_id)
                        if inp:
                            target_value = inp['value']
                            break
            
            if not target_value:
                # Fallback: try to match exact values if known or list available
                logger.warning(f"Could not find format matching '{file_format}'. Available options:")
                available = []
                for label in labels:
                     if 'SaveAsRadioButtonList' in label.get('for', ''):
                         available.append(label.get_text(strip=True))
                logger.warning(available)
                raise Exception(f"Format '{file_format}' not found.")

            # Prepare data for the second POST (Download)
            # We need new ViewState from the result page
            viewstate2 = result_soup.find('input', id='__VIEWSTATE')['value']
            eventvalidation2 = result_soup.find('input', id='__EVENTVALIDATION')['value']
            
            download_data = {
                '__VIEWSTATE': viewstate2,
                '__EVENTVALIDATION': eventvalidation2,
                'ctl00$ctl00$ContentPlaceHolderMain$CommandBar1$CommandBar1$SaveAsRadioButtonList': target_value,
                'ctl00$ctl00$ContentPlaceHolderMain$CommandBar1$CommandBar1$SaveAsBtn': 'Save result as...' 
            }
            
            logger.info(f"Download POST data: {download_data}")
            
            download_response = self.session.post(table_url, data=download_data)
            download_response.raise_for_status()
            
            return download_response.content
