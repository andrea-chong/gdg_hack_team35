from google import genai
from google.genai import types
from ast import literal_eval
import json

class ChatBot(genai.Client):

    def __init__(self, 
                project_id:str="ing-voice-team35",
                location:str="europe-west1"):
        try:
            self._api_client = genai.Client(
                vertexai=True,
                project=project_id,
                location=location
            )
            self.MODEL = "gemini-2.5-flash"
            self.DATASTORE_ID = "projects/307966155885/locations/global/collections/default_collection/dataStores/ing-website-chunks_1761746102597"
            self.SAFETY_SETTINGS = [types.SafetySetting(
                category="HARM_CATEGORY_HATE_SPEECH",
                threshold="OFF"
                ),types.SafetySetting(
                category="HARM_CATEGORY_DANGEROUS_CONTENT",
                threshold="OFF"
                ),types.SafetySetting(
                category="HARM_CATEGORY_SEXUALLY_EXPLICIT",
                threshold="OFF"
                ),types.SafetySetting(
                category="HARM_CATEGORY_HARASSMENT",
                threshold="OFF"
                )]
        except:
            raise

    def _parse_json(self, js_string:str):
        try:
            return json.loads(js_string)
        except json.JSONDecodeError:
            try:
                return literal_eval(js_string)
            except:
                print("error parsing json")
                return {}

    def retrieve_grounded_info(self, query:str):

        msg1_text1 = types.Part.from_text(text=query)
        contents = [
            types.Content(
            role="user",
            parts=[
                msg1_text1
            ]
            ),
        ]
        tools = [
            types.Tool(retrieval=types.Retrieval(vertex_ai_search=types.VertexAISearch(
                datastore=self.DATASTORE_ID))),
        ]

        generate_content_config = types.GenerateContentConfig(
            temperature = 1,
            top_p = 0.95,
            seed = 0,
            max_output_tokens = 65535,
            safety_settings = self.SAFETY_SETTINGS,
            tools = tools,
            system_instruction=[types.Part.from_text(
                text="""You are a helpful banking assistant with a wealth of knowledge about ING's products and processes. 
                Help to retrieve relevant information to support this customer's request."""
                )],
            thinking_config=types.ThinkingConfig(
            thinking_budget=-1,
            ),
        )

        response = []
        for chunk in self._api_client.models.generate_content_stream(
            model = self.MODEL,
            contents = contents,
            config = generate_content_config,
            ):
            if not chunk.candidates or not chunk.candidates[0].content or not chunk.candidates[0].content.parts:
                continue
            response.append(chunk)

        relevant_docs = []
        for r in response:
            grounding = r.candidates[0].grounding_metadata
            if grounding.grounding_chunks is not None:
                relevant_docs.extend(grounding.grounding_chunks)
                
        relevant_context = "\n\n".join( [doc.retrieved_context.text for doc in relevant_docs] )
        
        full_text = "\n".join([chunk.text for chunk in response])
        return full_text, relevant_context
    
    def classify_intent(self, query:str):

        intent_schema = {
        "description": "Schema for classifying the user's core intent.",
        "type": "OBJECT",
        "properties": {
            "intent": {
            "description": "The primary intent or category of the user's request.",
            "type": "STRING",
            "enum": [
                "Update customer information", #
                "Query for details about their existing product", #
                "Query for their account balance"
                "Query for details about their transactions", #
                "Get more information about the bank's product", #infomational
                "Block or stop a transaction or card", #
                "Speak to a human or create appointment at the branch", #
                "Something else"
            ]
            },
            "summary": {
            "description": "Summary of the customer's request",
            "type": "STRING"
            },
            "auth_required": {
            "type": "BOOLEAN"
            },
            "questions": {
            "description": "Questions to ask the customer",
            "type": "STRING"
            }
        },
        "required": [
            "intent",
            "summary",
            "auth_required"
        ]
        }

        sys_instruct = """You are a helpful banking assistant. Here more information about the SQL database you have access to and the fields available in each table:
        1. Customers table
        customer_id	STRING	REQUIRED	
        name	STRING	NULLABLE	
        birthdate	STRING	NULLABLE	(DD-MM-YYYY)
        email	STRING	NULLABLE	
        phone	STRING	NULLABLE	
        address	STRING	NULLABLE	
        segment_code	STRING	NULLABLE	(ADULT,CHILD,PROSPECT)

        2. Products table
        product_id	STRING	REQUIRED
        customer_id	STRING	REQUIRED
        product_type	STRING	REQUIRED
        product_name	STRING	REQUIRED
        opened_date	STRING	REQUIRED	(DD-MM-YYYY)
        status	STRING	REQUIRED

        3. Transactions table
        transaction_id	STRING	REQUIRED
        product_id	STRING	REQUIRED
        date	STRING	REQUIRED
        amount	FLOAT	REQUIRED
        currency	 STRING	REQUIRED
        description	STRING	NULLABLE
        transaction_type STRING REQUIRED (Credit,Debit)

        Classify the intention of this customer. Summarise their question retaining all information that is useful to help us generate a API request to complete their task. List questions to ask the customer for information we do not yet have but we require to help them perform the task."""
        
        generate_content_config = types.GenerateContentConfig(
            temperature = 1,
            top_p = 1,
            seed = 0,
            max_output_tokens = 65535,
            safety_settings = self.SAFETY_SETTINGS,
            response_mime_type = "application/json",
            response_schema = intent_schema,
            system_instruction=[types.Part.from_text(text=sys_instruct)],
            thinking_config=types.ThinkingConfig(
            thinking_budget=-1,
            ),
        )

        response = []
        for chunk in self._api_client.models.generate_content_stream(
            model = self.MODEL,
            contents = [
                types.Content(
                role="user",
                parts=[
                    types.Part.from_text(text=query)
                ]
                ),
            ],
            config = generate_content_config,
            ):
            if not chunk.candidates or not chunk.candidates[0].content or not chunk.candidates[0].content.parts:
                continue
            response.append(chunk.text)
        
        return " ".join(response)

    # def auth_dummy_prompt(self): ### Change to Dutch
    #     return "Please authenticate yourself by logging into your banking app."
    
    # def auth_dummy_response(self): ### Change to Dutch
    #     return "Thank you, you have been successfully authenticated."
    
    # def create_payload(intent,):
    #     payload_mapping = {

    #             "Update customer information", #
    #             "Query for details about their existing product", #
    #             "Query for details about their transactions", #
    #             "Get more information about the bank's product", #infomational
    #             "Block or stop a transaction or card", #
    #             "Speak to a human or create appointment at the branch", #
    #             "Something else"
    #         "Query for their account balance": {
    #             api: "/intent/balances.get",
    #             "payload": '{
    #                 "customer_id":"str",
    #                 "account_type":"str"
    #             }

    #     }

    def start_convo(self, query):
        info, relevant_docs = self.retrieve_grounded_info(query)
        intent_js = self._parse_json( self.classify_intent(query) )

        if (intent_js.get("intent", None) == "Something else") or (intent_js.get("intent", None) is None):
            return "Please try again I can help you with X Y Z"
        
        elif intent_js.get('auth_required'):
            return info,relevant_docs,intent_js
        
        elif intent_js.get('auth_required'):
            return info,relevant_docs,intent_js
        
        else:
            return "exception"
    
    