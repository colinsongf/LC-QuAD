'''
	In case of a goofup, kill - Priyansh (pc.priyansh@gmail.com)
	This file is used to quench all the LOD desires of the main scripts. So, mostly a class with several DBPedia functions. 

	FAQ:
	Q: Why is every sparql request under a "with" block?
	A: With ensures that the object is thrown away when the request is done. 
		Since we choose a different endpoint at every call, it's a good idea to throw it away after use. I'm just being finicky probably, but it wouldn't hurt

	Q: What's with the warnings?
	A: Because I can, bitch.
'''
from SPARQLWrapper import SPARQLWrapper, JSON
from operator import itemgetter
from pprint import pprint
import numpy as np
import traceback
import warnings
import pickle
import random
import redis
import json

#Our scripts
import natural_language_utilities as nlutils
import labels_mulitple_form

#GLOBAL MACROS
DBPEDIA_ENDPOINTS = ['http://dbpedia.org/sparql/','http://live.dbpedia.org/sparql/']
MAX_WAIT_TIME = 1.0

#SPARQL Templates
GET_PROPERTIES_OF_RESOURCE = '''SELECT DISTINCT ?property WHERE { %(target_resource)s ?property ?useless_resource }'''

GET_PROPERTIES_ON_RESOURCE = '''SELECT DISTINCT ?property WHERE { ?useless_resource  ?property %(target_resource)s }'''

GET_PROPERTIES_OF_RESOURCE_WITH_OBJECTS = '''SELECT DISTINCT ?property ?resource WHERE { %(target_resource)s ?property ?resource	}'''

GET_ENTITIES_OF_CLASS = '''SELECT DISTINCT ?entity WHERE {	?entity <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> %(target_class)s } '''

GET_LABEL_OF_RESOURCE = '''SELECT DISTINCT ?label WHERE { %(target_resource)s <http://www.w3.org/2000/01/rdf-schema#label> ?label . FILTER (lang(?label) = 'en')	} '''

GET_TYPE_OF_RESOURCE = '''SELECT DISTINCT ?type WHERE { %(target_resource)s <http://www.w3.org/1999/02/22-rdf-syntax-ns#type> ?type } '''

# GET_TYPE_OF_RESOURCE = '''SELECT DISTINCT ?type WHERE { %(target_resource)s <http://dbpedia.org/ontology/type> ?type } '''

GET_CLASS_PATH = '''SELECT DISTINCT ?type WHERE { %(target_class)s rdfs:subClassOf* ?type }'''

GET_SUPERCLASS = '''SELECT DISTINCT ?type WHERE { %(target_class)s rdfs:subClassOf ?type }'''

CHECK_URL = '''ASk {<%(target_resource)s> a owl:Thing} '''

class DBPedia:
	def __init__(self,_method='round-robin',_verbose=False,_db_name = 0):

		#Explanation: selection_method is used to select from the DBPEDIA_ENDPOINTS, hoping that we're not blocked too soon
		if _method in ['round-robin','random','select-one']:
			self.selection_method = _method
		else:
			warnings.warn("Selection method not understood, proceeding with 'select-one'")
			self.selection_method = 'select-one'

		self.verbose = _verbose
		self.sparql_endpoint = DBPEDIA_ENDPOINTS[0]
		self.r  = redis.StrictRedis(host='localhost', port=6379, db=_db_name)
		try:
			self.labels = pickle.load(open('resources/labels.pickle'))
		except:
			print "Label Cache not found. Creating a new one"
			traceback.print_exc()
			labels_mulitple_form.merge_multiple_forms()			#This should populate the dictionary with multiple form info and already pickle it
			self.labels = pickle.load(open('resources/labels.pickle'))
		self.fresh_labels = 0

	#initilizing the redis server.

	def select_sparql_endpoint(self):
		'''
			This function is to be called whenever we're making a call to DBPedia. Based on the selection mechanism selected at __init__,
			this function tells which endpoint to use at every point.
		'''
		if self.selection_method == 'round-robin':
			index = DBPEDIA_ENDPOINTS.index(self.sparql_endpoint)
			return DBPEDIA_ENDPOINTS[index+1] if index >= len(DBPEDIA_ENDPOINTS) else DBPEDIA_ENDPOINTS[0]

		if self.selection_method == 'select-one':
			return self.sparql_endpoint

	def shoot_custom_query(self, _custom_query):
		'''
			Shoot any custom query and get the SPARQL results as a dictionary
		'''
		caching_answer = self.r.get(_custom_query)
		if caching_answer:
			# print "@caching layer"
			return json.loads(caching_answer)
		sparql = SPARQLWrapper(self.select_sparql_endpoint())
		sparql.setQuery(_custom_query)
		sparql.setReturnFormat(JSON)
		caching_answer = sparql.query().convert()
		self.r.set(_custom_query,json.dumps(caching_answer))
		return caching_answer

	def get_properties_on_resource(self, _resource_uri):
		'''
			Fetch properties that point to this resource. 
			Eg. 
			Barack Obama -> Ex-President of -> _resource_uri would yield ex-president of as the relation
		'''
		if not nlutils.has_url(_resource_uri):
			warnings.warn("The passed resource %s is not a proper URI but is in shorthand. This is strongly discouraged." % _resource_uri)
			_resource_uri = nlutils.convert_shorthand_to_uri(_resource_uri)
		response = self.shoot_custom_query(GET_PROPERTIES_ON_RESOURCE % {'target_resource':_resource_uri})

	def get_properties_of_resource(self,_resource_uri,_with_connected_resource = False):
		'''
			This function can fetch the properties connected to this '_resource', in the format - _resource -> R -> O
			The boolean flag can be used if we want to return the (R,O) tuples instead of just R

			Return Type 
				if _with_connected_resource == True, [ [R,O], [R,O], [R,O] ...]
				else [ R,R,R,R...]
		'''
		#Check if the resource URI is shorthand or a proper URI
		temp_query = ""
		if not nlutils.has_url(_resource_uri):
			warnings.warn("The passed resource %s is not a proper URI but is in shorthand. This is strongly discouraged." % _resource_uri)
			_resource_uri = nlutils.convert_shorthand_to_uri(_resource_uri)

		#Prepare the SPARQL Request		sparql = SPARQLWrapper(self.select_sparql_endpoint())
		# with SPARQLWrapper(self.sparql_endpoint) as sparql:
		_resource_uri = '<'+_resource_uri+'>'
		if _with_connected_resource:
			temp_query = GET_PROPERTIES_OF_RESOURCE_WITH_OBJECTS % {'target_resource':_resource_uri}
		else:
			temp_query = GET_PROPERTIES_OF_RESOURCE % {'target_resource':_resource_uri}
		response = self.shoot_custom_query(temp_query)

		try:
			if _with_connected_resource:
				property_list = [ [x[u'property'][u'value'].encode('ascii','ignore'), x[u'resource'][u'value'].encode('ascii','ignore')] for x in response[u'results'][u'bindings'] ]
			else:
				property_list = [x[u'property'][u'value'].encode('ascii','ignore') for x in response[u'results'][u'bindings']]
		except:
			#TODO: Find and handle exceptions appropriately 
			traceback.print_exc()
		# pass

		return property_list

	def get_entities_of_class(self, _class_uri):
		'''
			This function can fetch the properties connected to the class passed as a function parameter _class_uri.

			Return Type
				[ S,S,S,S...]
		'''
		#Check if the resource URI is shorthand or a proper URI
		if not nlutils.has_url(_class_uri):
			warnings.warn("The passed class %s is not a proper URI but is in shorthand. This is strongly discouraged." % _class_uri)
			_class_uri = nlutils.convert_shorthand_to_uri(_class_uri)
		# with SPARQLWrapper(self.sparql_endpoint) as sparql:
		_class_uri = '<' + _class_uri + '>'
		response = self.shoot_custom_query(GET_ENTITIES_OF_CLASS % {'target_class':_class_uri})

		try:
			entity_list = [ x[u'entity'][u'value'].encode('ascii','ignore') for x in response[u'results'][u'bindings'] ]
		except:
			#TODO: Find and handle exceptions appropriately
			traceback.print_exc()
		# pass

		return entity_list

	def get_type_of_resource(self, _resource_uri, _filter_dbpedia = False):
		'''
			Function fetches the type of a given entity
			and can optionally filter out the ones of DBPedia only
		'''
		#@TODO: Add basic caching setup.
		if not nlutils.has_url(_resource_uri):
			warnings.warn("The passed resource %s is not a proper URI but probably a shorthand. This is strongly discouraged." % _resource_uri)
			_resource_uri = nlutils.convert_shorthand_to_uri(_resource_uri)
		_resource_uri = '<' + _resource_uri + '>'
		response = self.shoot_custom_query(GET_TYPE_OF_RESOURCE % {'target_resource': _resource_uri} )
		try:
			type_list = [ x[u'type'][u'value'].encode('ascii','ignore') for x in response[u'results'][u'bindings'] ]
		except:
			traceback.print_exc()



		#If we need only DBPedia's types
		if _filter_dbpedia:
			filtered_type_list = [x for x in type_list if x[:28] in ['http://dbpedia.org/ontology/','http://dbpedia.org/property/'] ]
			return filtered_type_list

		return type_list

	def get_answer(self, _sparql_query):
		'''
			Function used to shoot a query and get the answers back. Easy peasy.

			Return - array of values of first variable of query
			NOTE: Only give it queries with one variable
		'''
		try:
			response = self.shoot_custom_query(_sparql_query)
		except:
			traceback.print_exc()

		#Now to parse the response
		variables = [x for x in response[u'head'][u'vars']]

		#NOTE: Assuming that there's only one variable
		values = {}
		for index in xrange(0,len(variables)):
			value = [ x[variables[index]][u'value'].encode('ascii','ignore') for x in response[u'results'][u'bindings'] ]
			values[variables[index]] = value
		return values

	def get_label(self, _resource_uri):
		'''
			Function used to fetch the english label for a given resource.
			Not thoroughly tested tho.

			Also now it stores the labels in a pickled folder and 

			Always returns one value
		'''

		if not nlutils.has_url(_resource_uri):
			warnings.warn("The passed resource %s is not a proper URI but probably a shorthand. This is strongly discouraged." % _resource_uri)
			_resource_uri = nlutils.convert_shorthand_to_uri(_resource_uri)

		#Preparing the Query
		_resource_uri = '<'+_resource_uri+'>'
		
		#First try finding it in file
		try:
			label = np.random.choice(self.labels[_resource_uri[1:-1]])
			# print "Label for %s found in cache." % _resource_uri
			return label

		except KeyError:
			#Label not found in file. Throw it as a query to DBpedia
			try:
				response = self.shoot_custom_query(GET_LABEL_OF_RESOURCE % {'target_resource': _resource_uri})
			
				results = [x[u'label'][u'value'].encode('ascii','ignore') for x in response[u'results'][u'bindings'] ]
				if len(results) > 0:
					self.labels[_resource_uri[1:-1]] = results
				else:
					p = results[0]	#Should raise exception
				self.fresh_labels += 1

				if self.fresh_labels >= 100:
					f = open('resources/labels.pickle','w+')
					pickle.dump(self.labels, f)
					f.close()
					self.fresh_labels = 0
					print "Labels dumped to file."

				return np.random.choice(self.labels[_resource_uri[1:-1]])
			except IndexError as e:
				# print e
				# print _resource_uri, results
				# raw_input()
				return nlutils.get_label_via_parsing(_resource_uri)
				
			except:
				# print "in Exception"
				traceback.print_exc()
				# raw_input()
				return nlutils.get_label_via_parsing(_resource_uri)


		except:
			return nlutils.get_label_via_parsing(_resource_uri)
		

	def get_most_specific_class(self, _resource_uri):
		'''
			Query to find the most specific DBPedia Ontology class given a URI.
			Limitation: works only with resources.
			@TODO: Extend this to work with ontology (not entities) too. Or properties.
		'''
		# print _resource_uri
		if not nlutils.has_url(_resource_uri):
			warnings.warn("The passed resource %s is not a proper URI but probably a shorthand. This is strongly discouraged." % _resource_uri)
			_resource_uri = nlutils.convert_shorthand_to_uri(_resource_uri)

		#Get the DBpedia classes of resource
		classes = self.get_type_of_resource(_resource_uri, _filter_dbpedia = True)


		length_array = []	#A list of tuples, it's use explained below

		#For every class, find the length of path to owl:Thing.
		for class_uri in classes:

			#Preparing the query
			target_class = '<'+class_uri+'>'
			try:
				response = self.shoot_custom_query(GET_CLASS_PATH % {'target_class':target_class})
			except:
				traceback.print_exc()

			#Parsing the Result
			try:
				results = [x[u'type'][u'value'].encode('ascii','ignore') for x in response[u'results'][u'bindings'] ]

			except:
				traceback.print_exc()

			#Count the number of returned classes and store it in treturn max(length_array,key=itemgetter(1))[0]he list.
			length_array.append( (class_uri,len(results)) )
		# pprint(length_array)
		if len(length_array) > 0:
			return max(length_array,key=itemgetter(1))[0]
		else:
			#if there is no results from the filter type , return it as owl Thing 
			return "http://www.w3.org/2002/07/owl#Thing"

	def is_common_parent(self,_resource_uri_1 , _resource_uri_2):
		specific_class_uri_1 = "<" + self.get_most_specific_class(_resource_uri_1) + ">"
		specific_class_uri_2 = "<" + self.get_most_specific_class(_resource_uri_2) + ">"
		try:
			response_uri_1 = self.shoot_custom_query(GET_SUPERCLASS % {'target_class': specific_class_uri_1})
			response_uri_2 = self.shoot_custom_query(GET_SUPERCLASS % {'target_class': specific_class_uri_2})
		except:
			traceback.print_exc()

		#Parsing the results
		try:
			results_1 = [x[u'type'][u'value'].encode('ascii','ignore') for x in response_uri_1[u'results'][u'bindings'] ]
			results_2 = [x[u'type'][u'value'].encode('ascii', 'ignore') for x in
						 response_uri_2[u'results'][u'bindings']]
		except:
			traceback.print_exc()
		filtered_type_list_1 = [x for x in results_1 if
							  x[:28] in ['http://dbpedia.org/ontology/', 'http://dbpedia.org/property/']]
		filtered_type_list_2 = [x for x in results_2 if
							  x[:28] in ['http://dbpedia.org/ontology/', 'http://dbpedia.org/property/']]
		if filtered_type_list_1 == filtered_type_list_2 :
			return True
		else:
			return False

	def get_parent(self,_resource_uri):
		specific_class_uri_1 = "<" + self.get_most_specific_class(_resource_uri) + ">"
		try:
			response_uri_1 = self.shoot_custom_query(GET_SUPERCLASS % {'target_class': specific_class_uri_1})
		except:
			print traceback.print_exception()
		try:
			results_1 = [x[u'type'][u'value'].encode('ascii', 'ignore') for x in
						 response_uri_1[u'results'][u'bindings']]
		except:
			print traceback.print_exception()
		filtered_type_list_1 = [x for x in results_1 if
								x[:28] in ['http://dbpedia.org/ontology/', 'http://dbpedia.org/property/']]
		if len(filtered_type_list_1) >= 1:
			return  filtered_type_list_1[0]
		else:
			if filtered_type_list_1:
				return filtered_type_list_1
			else:
				return "http://www.w3.org/2002/07/owl#Thing"

	def is_Url(self,url):
		response = self.shoot_custom_query(CHECK_URL % {'target_resource':url})
		return response["boolean"]



if __name__ == '__main__':
	pass
	# print "\n\nBill Gates"
	dbp = DBPedia()
	# pprint(dbp.get_type_of_resource('http://dbpedia.org/resource/M._J._P._Rohilkhand_University', _filter_dbpedia = True))
	# print "\n\nIndia"
	# pprint(dbp.get_type_of_resource('http://dbpedia.org/resource/India', _filter_dbpedia = True))
    #
	# q = 'SELECT DISTINCT ?uri, ?a WHERE { ?uri <http://dbpedia.org/ontology/birthPlace> <http://dbpedia.org/resource/Mengo,_Uganda> . ?uri <http://dbpedia.org/ontology/birthPlace> ?a }'
	# pprint(dbp.get_answer(q))
    #
    #
	uri = 'http://dbpedia.org/resource/Donald_Trump'
	# print dbp.get_most_specific_class(uri)
    #
	# q = 'http://dbpedia.org/ontology/birthPlace'
	# pprint(dbp.get_label(q))
	# q = 'http://dbpedia.org/resource/Mumbai'
	print dbp.get_parent(uri)
	# r = 'http://dbpedia.org/resource/India'
